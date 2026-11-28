"""Appends and wipes the generated demo diary history inside Journal.

Runs in the journal-api container (the run_db pattern of
tools/rebuild_demo_timetable.py: docker compose exec journal-api
/app/.venv/bin/python -c <source> with JSON on stdin):

- generate: {"mode": "generate", "export": {...}, "manifest": {...}} where
  `export` is the output of the diary_export mode of
  tools/balance_demo_lessons_db.py (lessons of the demo classes of the
  window [September 1, cutoff] with statuses and school dates) and
  `manifest` is .demo-data/expanded-school.json (demo classes and the
  year fingerprint). The walk is deterministic and append-only: it plans
  rows for every planned lesson of a manifest class that has no rows
  yet (live teacher rows block a lesson forever), keeps the density of
  2-4 grades per student per week (counted over the already-written
  rows), guarantees at least one grade per subject per quarter, adds
  periodic class-wide control works and precomputed absence episodes
  (illness of 1-2 weekdays with a reason). Rows are inserted in chunks
  of lessons in separate transactions with generator=true; the report
  carries the rosters for the homework history generator. A rerun
  without a cutoff movement inserts nothing.
- wipe: input {"mode": "wipe"} - deletes every generator row
  (attendance and grades) of both tables in one transaction.

The manifest calendar version must equal the Journal copy
(journal_service.domain.study_quarters): a mismatch means the yearly
reseed is due and the run refuses instead of writing stale history.

Service imports are deferred, so the module stays importable outside
the container for unit tests.
"""

import asyncio
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import UUID

# Плотность оценок: суммарно на ученика в неделю (спецификация дневника).
WEEKLY_MIN = 2
WEEKLY_MAX = 4
# Контрольная — на каждом CONTROL_PERIOD-м уроке предмета в четверти.
CONTROL_PERIOD = 12
# Гарантия «хотя бы одна оценка по предмету за четверть»: оценка ставится
# не позже GUARANTEE_MAX-го присутственного урока предмета в четверти.
GUARANTEE_MAX = 4
# Эпизоды отсутствия на год: 2-3 по 1-2 будних дня с причиной.
ABSENCE_EPISODES_MIN = 2
ABSENCE_EPISODES_MAX = 3
# Уроков на транзакцию записи.
CHUNK_LESSONS = 500
# Batch size of IN () statements (see balance_demo_lessons_db.py).
SQL_BATCH_SIZE = 1000


def in_batches(values, size: int = SQL_BATCH_SIZE):
    """Yields the values in batches of at most size, order preserved."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


def stable_hash(*parts: str) -> int:
    """Deterministic hash of the parts, stable across runs and cutoffs."""
    payload = "|".join(str(part) for part in parts)
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big")


def profile_level(student: str) -> int:
    """Base performance level of a student: 3, 4 or 5.

    Shared with the homework history generator (the same profile per
    student in both histories); duplicated there because container
    tools run as standalone source without cross-imports.
    """
    return 3 + stable_hash("profile", student) % 3


def profile_grade(student: str, lesson_key: str) -> int:
    """One grade of the student profile: level +- 1, clamped to 2..5."""
    level = profile_level(student)
    return max(2, min(5, level + stable_hash("grade", student, lesson_key) % 3 - 1))


def weekly_target(student: str, week: date) -> int:
    """Weekly grade budget of the student: 2..4, stable per week."""
    span = WEEKLY_MAX - WEEKLY_MIN + 1
    return WEEKLY_MIN + stable_hash("week", student, week.isoformat()) % span


def guaranteed_lesson_index(student: str, subject_id: int, quarter: int) -> int:
    """The 1..GUARANTEE_MAX-th present lesson of the subject that must be graded."""
    return 1 + stable_hash("guarantee", student, subject_id, quarter) % GUARANTEE_MAX


def absence_episode_dates(
    student: str, year_start: date, year_end: date
) -> dict[date, str]:
    """Precomputes the absence dates of a student for the whole study year.

    Episodes: 2-3 per year, 1-2 days each, anchored to a weekday of the
    study year (Sundays are skipped: there are no lessons). Reasons:
    mostly illness, sometimes excused, rarely unexcused. The result
    depends only on the student and the year bounds, never on the
    export cutoff, so the walk converges on reruns.
    """
    days = (year_end - year_start).days
    if days <= 0:
        return {}
    episodes: dict[date, str] = {}
    count = ABSENCE_EPISODES_MIN + stable_hash("absence-count", student) % (
        ABSENCE_EPISODES_MAX - ABSENCE_EPISODES_MIN + 1
    )
    for index in range(count):
        anchor = year_start + timedelta(
            days=stable_hash("absence-start", student, index) % (days + 1)
        )
        while anchor.weekday() == 6:  # воскресенье — не учебный день
            anchor += timedelta(days=1)
        length = 1 + stable_hash("absence-len", student, index) % 2
        reason = stable_hash("absence-reason", student, index) % 10
        status = (
            "absent_sick"
            if reason < 7
            else "absent_excused"
            if reason < 9
            else "absent_unexcused"
        )
        for offset in range(length):
            day = anchor + timedelta(days=offset)
            if day.weekday() != 6:
                episodes.setdefault(day, status)
    return episodes


def parse_lessons(raw_lessons) -> list[dict]:
    """Validates and orders the export lessons chronologically."""
    lessons = []
    for raw in raw_lessons:
        lessons.append(
            {
                "lesson_id": int(raw["lesson_id"]),
                "class_id": int(raw["class_id"]),
                "subject_id": int(raw["subject_id"]),
                "teacher_id": str(UUID(raw["teacher_id"])),
                "date": date.fromisoformat(raw["date"]),
                "starts_at": datetime.fromisoformat(raw["starts_at"]),
                "status": str(raw["status"]),
            }
        )
    lessons.sort(key=lambda row: (row["starts_at"], row["lesson_id"]))
    return lessons


def manifest_class_ids(manifest: dict) -> set[int]:
    """Returns the demo class ids of the expanded-school manifest."""
    return {int(row["id"]) for row in manifest.get("classes", [])}


def check_calendar_version(manifest: dict, calendar_version: int) -> None:
    """Refuses the run when the manifest and Journal calendars diverge.

    Raises:
        ValueError: The year fingerprint is missing or its calendar
            version differs - the yearly reseed is due.
    """
    fingerprint = manifest.get("year_fingerprint") or {}
    manifest_version = fingerprint.get("calendar_version")
    if manifest_version is None or int(manifest_version) != calendar_version:
        raise ValueError(
            f"Manifest calendar version {manifest_version!r} does not equal "
            f"Journal copy {calendar_version}: the yearly reseed is due"
        )


def quarter_number(day: date, quarters: list[tuple[date, date]]) -> int:
    """Returns the quarter (1..4) that owns the school date.

    Raises:
        ValueError: The date leaves every quarter (vacation or outside
            the study year) - the export must carry only school days.
    """
    for number, (start, end) in enumerate(quarters, start=1):
        if start <= day <= end:
            return number
    raise ValueError(f"date {day} leaves every quarter of the study year")


def plan_diary(
    lessons: list[dict],
    rosters: dict[int, list[str]],
    existing_attendance: list[tuple[int, str, str]],
    existing_grades: list[tuple[int, str, str]],
    cutoff: date,
    quarters: list[tuple[date, date]],
    year_start: date,
    year_end: date,
) -> tuple[list[dict], list[dict], dict]:
    """Plans the new rows of the deterministic diary walk.

    Every planned lesson gets attendance for its whole roster and the
    decided grades; lessons with any existing rows (live or generator),
    non-planned lessons and lessons past the cutoff are skipped and
    counted. The density state is recomputed from the already-written
    rows, so a rerun plans nothing until the cutoff moves.

    Returns:
        (attendance rows, grade rows, walk report) - the rows carry
        lesson_id, student_id and the decided values, ready for insert.
    """
    attendance_state: dict[tuple[int, str], str] = {}
    for lesson_id, student_id, status in existing_attendance:
        attendance_state[(lesson_id, student_id)] = status
    grades_state: dict[tuple[int, str], list[str]] = {}
    for lesson_id, student_id, kind in existing_grades:
        grades_state.setdefault((lesson_id, student_id), []).append(kind)

    lesson_by_id = {lesson["lesson_id"]: lesson for lesson in lessons}
    week_counts: dict[tuple[str, date], int] = {}
    subject_quarter: dict[tuple[str, int, int], int] = {}
    present_index: dict[tuple[str, int, int], int] = {}
    absences: dict[str, dict[date, str]] = {}

    def count_grade(student: str, lesson: dict) -> None:
        week = lesson["date"] - timedelta(days=lesson["date"].weekday())
        week_counts[(student, week)] = week_counts.get((student, week), 0) + 1
        quarter = quarter_number(lesson["date"], quarters)
        key = (student, lesson["subject_id"], quarter)
        subject_quarter[key] = subject_quarter.get(key, 0) + 1

    def count_present(student: str, lesson: dict) -> None:
        quarter = quarter_number(lesson["date"], quarters)
        key = (student, lesson["subject_id"], quarter)
        present_index[key] = present_index.get(key, 0) + 1

    # Существующие строки задают стартовое состояние плотности.
    for (lesson_id, student_id), status in attendance_state.items():
        lesson = lesson_by_id.get(lesson_id)
        if lesson is not None and status == "present":
            count_present(student_id, lesson)
    for (lesson_id, student_id), kinds in grades_state.items():
        lesson = lesson_by_id.get(lesson_id)
        if lesson is not None:
            for _kind in kinds:
                count_grade(student_id, lesson)

    # Индекс урока внутри (класс, предмет, четверть) от начала четверти.
    subject_counter: dict[tuple[int, int, int], int] = {}
    control_lesson_ids: set[int] = set()
    for lesson in lessons:
        if lesson["status"] != "planned" or lesson["date"] > cutoff:
            continue
        quarter = quarter_number(lesson["date"], quarters)
        key = (lesson["class_id"], lesson["subject_id"], quarter)
        subject_counter[key] = subject_counter.get(key, 0) + 1
        if subject_counter[key] % CONTROL_PERIOD == 0:
            control_lesson_ids.add(lesson["lesson_id"])

    attendance_rows: list[dict] = []
    grade_rows: list[dict] = []
    report = {
        "lessons_total": len(lessons),
        "lessons_not_planned": 0,
        "lessons_after_cutoff": 0,
        "lessons_with_rows": 0,
        "lessons_written": 0,
        "foreign_class_lessons": 0,
    }
    for lesson in lessons:
        if lesson["status"] != "planned":
            report["lessons_not_planned"] += 1
            continue
        if lesson["date"] > cutoff:
            report["lessons_after_cutoff"] += 1
            continue
        lesson_id = lesson["lesson_id"]
        roster = rosters.get(lesson["class_id"])
        if roster is None:
            report["foreign_class_lessons"] += 1
            continue
        if any((lesson_id, student) in attendance_state for student in roster) or any(
            (lesson_id, student) in grades_state for student in roster
        ):
            report["lessons_with_rows"] += 1
            continue
        quarter = quarter_number(lesson["date"], quarters)
        week = lesson["date"] - timedelta(days=lesson["date"].weekday())
        is_control = lesson_id in control_lesson_ids
        for student in roster:
            episode = absences.get(student)
            if episode is None:
                episode = absence_episode_dates(student, year_start, year_end)
                absences[student] = episode
            status = episode.get(lesson["date"], "present")
            attendance_state[(lesson_id, student)] = status
            attendance_rows.append(
                {
                    "lesson_id": lesson_id,
                    "lesson_date": lesson["date"],
                    "class_id": lesson["class_id"],
                    "student_id": student,
                    "status": status,
                    "author_id": lesson["teacher_id"],
                }
            )
            if status != "present":
                continue
            count_present(student, lesson)
            written = week_counts.get((student, week), 0)
            target = weekly_target(student, week)
            subject_key = (student, lesson["subject_id"], quarter)
            lesson_key = str(lesson_id)
            grade: int | None = None
            kind: str | None = None
            if is_control and written < WEEKLY_MAX:
                grade = profile_grade(student, lesson_key)
                kind = "control"
            elif (
                subject_quarter.get(subject_key, 0) == 0
                and present_index.get(subject_key, 0)
                >= guaranteed_lesson_index(student, lesson["subject_id"], quarter)
                and written < WEEKLY_MAX
            ):
                grade = profile_grade(student, lesson_key)
                kind = "oral"
            elif written < target and (
                written < WEEKLY_MIN
                or stable_hash("fill", student, lesson_key) % 3 == 0
            ):
                grade = profile_grade(student, lesson_key)
                kind = (
                    "written"
                    if stable_hash("kind", student, lesson_key) % 2 == 0
                    else "oral"
                )
            if grade is not None and kind is not None:
                grade_rows.append(
                    {
                        "lesson_id": lesson_id,
                        "lesson_date": lesson["date"],
                        "class_id": lesson["class_id"],
                        "subject_id": lesson["subject_id"],
                        "student_id": student,
                        "grade": grade,
                        "kind": kind,
                        "author_id": lesson["teacher_id"],
                    }
                )
                grades_state.setdefault((lesson_id, student), []).append(kind)
                count_grade(student, lesson)
        report["lessons_written"] += 1
    report["attendance_rows"] = len(attendance_rows)
    report["grade_rows"] = len(grade_rows)
    return attendance_rows, grade_rows, report


# ------------------------------------------------- container bindings


class SqlDiaryStore:
    """All generate/wipe SQL of the tool against one open session.

    The service rows are imported on construction: the module stays
    importable outside the journal container (unit tests run without
    SQLAlchemy and drive the runs with fakes).
    """

    def __init__(self, session) -> None:
        from journal_service.infrastructure.models.lesson_record import (
            LessonAttendanceRow,
            LessonGradeRow,
        )
        from journal_service.infrastructure.models.school_class import ClassRow
        from journal_service.infrastructure.models.student_class_period import (
            StudentClassPeriodRow,
        )

        self._session = session
        self._attendance_row = LessonAttendanceRow
        self._grade_row = LessonGradeRow
        self._period_row = StudentClassPeriodRow
        # FK lesson_attendance.class_id указывает на classes: таблица должна
        # быть зарегистрирована в метаданных до вставки, иначе SQLAlchemy не
        # разрешит внешний ключ.
        self._class_row = ClassRow

    async def rosters_of_classes(self, class_ids) -> dict[int, list[str]]:
        """Current rosters: open class periods per class, ordered by id."""
        from sqlalchemy import select

        statement = (
            select(self._period_row.class_id, self._period_row.student_id)
            .where(
                self._period_row.class_id.in_(class_ids),
                self._period_row.left_at.is_(None),
            )
            .order_by(self._period_row.class_id, self._period_row.id)
        )
        rows = (await self._session.execute(statement)).all()
        rosters: dict[int, list[str]] = {}
        for class_id, student_id in rows:
            rosters.setdefault(class_id, []).append(str(student_id))
        return rosters

    async def existing_rows(self, lesson_ids) -> tuple[list, list]:
        """Already-written attendance and grades of the export lessons."""
        from sqlalchemy import select

        attendance: list[tuple[int, str, str]] = []
        grades: list[tuple[int, str, str]] = []
        for batch in in_batches(lesson_ids):
            attendance.extend(
                (row[0], str(row[1]), row[2].value)
                for row in (
                    await self._session.execute(
                        select(
                            self._attendance_row.lesson_id,
                            self._attendance_row.student_id,
                            self._attendance_row.status,
                        ).where(self._attendance_row.lesson_id.in_(batch))
                    )
                ).all()
            )
            grades.extend(
                (row[0], str(row[1]), row[2].value)
                for row in (
                    await self._session.execute(
                        select(
                            self._grade_row.lesson_id,
                            self._grade_row.student_id,
                            self._grade_row.kind,
                        ).where(self._grade_row.lesson_id.in_(batch))
                    )
                ).all()
            )
        return attendance, grades

    async def insert_attendance(self, rows: list[dict]) -> None:
        """Adds the attendance rows of one chunk in the open transaction."""
        from journal_service.domain.lesson_records import AttendanceStatus

        self._session.add_all(
            [
                self._attendance_row(
                    lesson_id=row["lesson_id"],
                    lesson_date=row["lesson_date"],
                    class_id=row["class_id"],
                    student_id=UUID(row["student_id"]),
                    status=AttendanceStatus(row["status"]),
                    generator=True,
                    author_id=UUID(row["author_id"]),
                )
                for row in rows
            ]
        )
        await self._session.flush()

    async def insert_grades(self, rows: list[dict]) -> None:
        """Adds the grade rows of one chunk in the open transaction."""
        from journal_service.domain.lesson_records import GradeKind

        self._session.add_all(
            [
                self._grade_row(
                    lesson_id=row["lesson_id"],
                    lesson_date=row["lesson_date"],
                    class_id=row["class_id"],
                    subject_id=row["subject_id"],
                    student_id=UUID(row["student_id"]),
                    grade=row["grade"],
                    kind=GradeKind(row["kind"]),
                    generator=True,
                    author_id=UUID(row["author_id"]),
                )
                for row in rows
            ]
        )
        await self._session.flush()

    async def delete_generator_rows(self) -> tuple[int, int]:
        """Deletes every generator row of both tables, attendance first."""
        from sqlalchemy import delete

        attendance = (
            await self._session.execute(
                delete(self._attendance_row).where(
                    self._attendance_row.generator.is_(True)
                )
            )
        ).rowcount or 0
        grades = (
            await self._session.execute(
                delete(self._grade_row).where(self._grade_row.generator.is_(True))
            )
        ).rowcount or 0
        return attendance, grades


async def run_generate(
    store_factory, session_factory, export: dict, manifest: dict, quarters, year_bounds
) -> dict:
    """Plans the walk and inserts the rows in per-lesson-chunk transactions.

    A chunk error rolls back only that chunk; the run stops with the
    remaining lesson count for a rerun (written lessons are skipped, so
    the rerun continues instead of restarting).
    """
    lessons = parse_lessons(export["lessons"])
    cutoff = date.fromisoformat(export["cutoff"])
    year_start, year_end = year_bounds
    class_ids = manifest_class_ids(manifest)
    if not class_ids:
        raise ValueError("The manifest carries no demo classes")

    async with session_factory() as session:
        store = store_factory(session)
        rosters = await store.rosters_of_classes(sorted(class_ids))
        attendance, grades = await store.existing_rows(
            [lesson["lesson_id"] for lesson in lessons]
        )
    planned_attendance, planned_grades, report = plan_diary(
        lessons, rosters, attendance, grades, cutoff, quarters, year_start, year_end
    )

    attendance_by_lesson: dict[int, list[dict]] = defaultdict(list)
    for row in planned_attendance:
        attendance_by_lesson[row["lesson_id"]].append(row)
    grades_by_lesson: dict[int, list[dict]] = defaultdict(list)
    for row in planned_grades:
        grades_by_lesson[row["lesson_id"]].append(row)
    lesson_order = list(attendance_by_lesson)

    inserted_attendance = 0
    inserted_grades = 0
    chunks_inserted = 0
    failed_chunk: dict | None = None
    remaining = 0
    for start in range(0, len(lesson_order), CHUNK_LESSONS):
        chunk = lesson_order[start : start + CHUNK_LESSONS]
        wanted = set(chunk)
        try:
            async with session_factory() as session, session.begin():
                store = store_factory(session)
                await store.insert_attendance(
                    [row for row in planned_attendance if row["lesson_id"] in wanted]
                )
                await store.insert_grades(
                    [row for row in planned_grades if row["lesson_id"] in wanted]
                )
        except Exception as error:  # noqa: BLE001 - reported, not raised
            failed_chunk = {"index": chunks_inserted, "error": str(error)}
            remaining = len(lesson_order) - start
            break
        inserted_attendance += sum(
            len(attendance_by_lesson[lesson_id]) for lesson_id in chunk
        )
        inserted_grades += sum(len(grades_by_lesson[lesson_id]) for lesson_id in chunk)
        chunks_inserted += 1
    return {
        **report,
        "cutoff": cutoff.isoformat(),
        "classes": len(rosters),
        "students": sum(len(students) for students in rosters.values()),
        "rosters": {
            str(class_id): students for class_id, students in sorted(rosters.items())
        },
        "attendance_inserted": inserted_attendance,
        "grades_inserted": inserted_grades,
        "chunks_inserted": chunks_inserted,
        "failed_chunk": failed_chunk,
        "remaining_lessons": remaining,
    }


async def run_wipe(store_factory, session_factory) -> dict:
    """Deletes every generator row of both tables in one transaction."""
    async with session_factory() as session, session.begin():
        store = store_factory(session)
        attendance, grades = await store.delete_generator_rows()
    return {"attendance_deleted": attendance, "grades_deleted": grades}


async def main():
    from journal_service.config import JournalSettings
    from journal_service.domain import study_quarters
    from journal_service.infrastructure.database import (
        create_engine,
        create_session_factory,
    )

    data = json.load(sys.stdin)
    engine = create_engine(JournalSettings().database_url)
    sessions = create_session_factory(engine)
    try:
        if data["mode"] == "wipe":
            print(json.dumps(await run_wipe(SqlDiaryStore, sessions)))
            return
        if data["mode"] != "generate":
            raise SystemExit(f"Unsupported mode: {data['mode']!r}")
        check_calendar_version(data["manifest"], study_quarters.CALENDAR_VERSION)
        quarters = [tuple(bounds) for bounds in study_quarters.QUARTERS]
        result = await run_generate(
            SqlDiaryStore,
            sessions,
            data["export"],
            data["manifest"],
            quarters,
            study_quarters.STUDY_YEAR,
        )
        print(json.dumps(result))
        if result["failed_chunk"] is not None:
            # Отчёт уже напечатан; ненулевой код сообщает оркестратору,
            # что история неполная и нужен повторный запуск.
            raise SystemExit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
