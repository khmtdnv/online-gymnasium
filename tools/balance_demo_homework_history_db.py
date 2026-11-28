"""Appends the generated demo homework history inside Homework.

Runs in the homework-api container (the run_db pattern of
tools/rebuild_demo_timetable.py: docker compose exec homework-api
/app/.venv/bin/python -c <source> with JSON on stdin):

    {"mode": "generate", "export": {...}, "manifest": {...},
     "rosters": {"<class_id>": ["<student uuid>", ...]}}

`export` is the output of the diary_export mode of
tools/balance_demo_lessons_db.py (it carries the calendar version of
the Schedule module), `manifest` is .demo-data/expanded-school.json
and `rosters` comes from the report of tools/balance_demo_diary_db.py
(Journal knows the class rosters, Homework does not).

The walk is deterministic and append-only: an assignment is issued on
every ~4th-5th lesson of a subject (counted over the chronological
stream from the study-year start, never from the cutoff), the author
is the lesson teacher (a demo teacher), the deadline is the next
lesson of the subject or a manual datetime three days later. Answers
are written directly with the same per-student profile as the diary
generator (duplicated pure helpers - container tools run as
standalone source); the synthesized fields mirror the public API
exactly: idempotency keys are printable, request hashes are the sha256
fingerprints of the submit command, attempt numbering follows the
returned -> regraded flow, and the CHECK invariants hold (returned
carries a non-empty teacher comment, graded carries reviewer and
time). Homework of lessons that already have an assignment is skipped;
no outbox events are written - only live teacher reviews emit events.

The rollback is the wipe mode of tools/balance_homework_scenarios_db.py
(demo teacher x demo class) with the scenario reseed of
tools/create_demo_data.py - see the runbook.

Service imports are deferred, so the module stays importable outside
the container for unit tests.
"""

import asyncio
import hashlib
import json
import sys
from datetime import date, datetime, timedelta
from uuid import UUID

# Выдача ДЗ: период 4 или 5 уроков предмета, стабильный для предмета
# года (в среднем каждый ~4.6-й урок предмета).
HOMEWORK_PERIOD = 5
# Ответы: доли сценариев на сотню (полный цикл — только при прошедшем сроке);
# остальные 30 из сотни остаются без ответа — «не сдано» в дневнике.
GRADED_SHARE = 45
RETURNED_SHARE = 10
RETURN_REGRADED_SHARE = 5
SUBMITTED_SHARE = 10
# Заданий на транзакцию записи.
CHUNK_HOMEWORK = 200
# Batch size of IN () statements (see balance_demo_lessons_db.py).
SQL_BATCH_SIZE = 1000

DESCRIPTIONS = (
    "Повторить параграф и выполнить упражнения после него.",
    "Решить задачи из рабочего листа, записать ход решения.",
    "Выучить правило и составить пять своих примеров.",
    "Прочитать текст и письменно ответить на вопросы.",
    "Подготовить краткое сообщение по теме урока.",
)
ANSWER_TEXTS = (
    "Выполнено в тетради, решение записано полностью.",
    "Задания решены, ответы проверены самостоятельно.",
    "Работа готова, труднее всего далась последняя задача.",
    "Выполнено частично: не хватило времени на финальный пункт.",
)
RETURN_COMMENTS = (
    "Не хватает решения третьей задачи - допишите ход рассуждений.",
    "Работа сделана небрежно, перепишите аккуратнее.",
    "Ответ верный, но запись решения неполная - восстановите шаги.",
)


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

    Duplicated from tools/balance_demo_diary_db.py: the diary grades and
    the homework review grades share the same per-student profile.
    """
    return 3 + stable_hash("profile", student) % 3


def profile_grade(student: str, lesson_key: str) -> int:
    """One grade of the student profile: level +- 1, clamped to 2..5."""
    level = profile_level(student)
    return max(2, min(5, level + stable_hash("grade", student, lesson_key) % 3 - 1))


def request_fingerprint(homework_id: int, student_id: str, answer_text: str) -> str:
    """Computes the request hash exactly like the submit-answer API."""
    payload = {
        "answer_text": answer_text,
        "files": [],
        "homework_id": homework_id,
        "student_id": student_id,
    }
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def answer_idempotency_key(lesson_id: int, student_id: str, attempt: int) -> str:
    """Stable printable key of one generated attempt."""
    return f"demo-history-{lesson_id}-{student_id}-{attempt}"


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


def check_calendar_version(export: dict, manifest: dict) -> None:
    """Refuses the run when the manifest and export calendars diverge.

    Raises:
        ValueError: The year fingerprint is missing or its calendar
            version differs from the export - the yearly reseed is due.
    """
    fingerprint = manifest.get("year_fingerprint") or {}
    manifest_version = fingerprint.get("calendar_version")
    export_version = export.get("calendar_version")
    if manifest_version is None or export_version is None:
        raise ValueError("Calendar version is missing in the manifest or export")
    if int(manifest_version) != int(export_version):
        raise ValueError(
            f"Manifest calendar version {manifest_version!r} does not equal "
            f"export version {export_version!r}: the yearly reseed is due"
        )


def _submitted_at(lesson: dict, student: str, attempt: int) -> datetime:
    """Deterministic submission moment: hours after the issuing lesson."""
    return lesson["starts_at"] + timedelta(
        hours=2
        + stable_hash("hw-submitted", student, str(lesson["lesson_id"]), attempt) % 24
    )


def _reviewed_at(submitted_at: datetime, lesson: dict, student: str, attempt: int):
    """Deterministic review moment: hours after the submission."""
    return submitted_at + timedelta(
        hours=1
        + stable_hash("hw-reviewed", student, str(lesson["lesson_id"]), attempt) % 12
    )


def homework_period(class_id: int, subject_id: int) -> int:
    """Период выдачи предмету: 4 или 5 уроков, стабильный на весь год."""
    return 4 if stable_hash("hw-period", class_id, subject_id) % 3 == 0 else 5


def plan_homework(
    lessons: list[dict],
    rosters: dict[int, list[str]],
    existing_homework_lessons: set[int],
    cutoff: date,
) -> tuple[list[dict], dict]:
    """Plans the assignments with answers of the deterministic walk.

    Returns:
        (planned assignments, report) - every assignment carries its
        answers; times are computed past moments of the lesson stream.
    """
    by_subject: dict[tuple[int, int], list[dict]] = {}
    report = {
        "lessons_total": len(lessons),
        "lessons_not_planned": 0,
        "lessons_after_cutoff": 0,
        "assignments_skipped_existing": 0,
        "assignments_planned": 0,
    }
    for lesson in lessons:
        if lesson["status"] != "planned":
            report["lessons_not_planned"] += 1
        elif lesson["date"] > cutoff:
            report["lessons_after_cutoff"] += 1
        else:
            by_subject.setdefault(
                (lesson["class_id"], lesson["subject_id"]), []
            ).append(lesson)

    planned: list[dict] = []
    for (class_id, subject_id), stream in sorted(by_subject.items()):
        period = homework_period(class_id, subject_id)
        for index, lesson in enumerate(stream, start=1):
            due_lesson = stream[index] if index < len(stream) else None
            if index % period != 0:
                continue
            if lesson["lesson_id"] in existing_homework_lessons:
                report["assignments_skipped_existing"] += 1
                continue
            roster = rosters.get(class_id)
            if roster is None:
                continue
            assignment = {
                "lesson": lesson,
                "due_lesson": due_lesson,
                "description": DESCRIPTIONS[
                    stable_hash("hw-desc", class_id, subject_id, index)
                    % len(DESCRIPTIONS)
                ],
                "answers": [],
            }
            for student in roster:
                mix = stable_hash("hw-answer", student, lesson["lesson_id"]) % 100
                if mix >= (
                    GRADED_SHARE
                    + RETURNED_SHARE
                    + RETURN_REGRADED_SHARE
                    + SUBMITTED_SHARE
                ):
                    continue  # без ответа — «не сдано» в дневнике
                # Полный цикл — только при прошедшем сроке. Ручной срок
                # (следующего урока нет в окне экспорта) всегда впереди.
                full_cycle = due_lesson is not None and due_lesson["date"] <= cutoff
                if not full_cycle:
                    # Срок ещё впереди: ответ есть, проверки ещё нет.
                    submitted = _submitted_at(lesson, student, 1)
                    assignment["answers"].append(
                        {
                            "student_id": student,
                            "attempt": 1,
                            "status": "submitted",
                            "grade": None,
                            "answer_text": ANSWER_TEXTS[
                                stable_hash("hw-text", student, lesson["lesson_id"], 1)
                                % len(ANSWER_TEXTS)
                            ],
                            "teacher_comment": "",
                            "reviewer_id": None,
                            "submitted_at": submitted,
                            "reviewed_at": None,
                            "idempotency_key": answer_idempotency_key(
                                lesson["lesson_id"], student, 1
                            ),
                        }
                    )
                    continue
                if mix < GRADED_SHARE:
                    submitted = _submitted_at(lesson, student, 1)
                    assignment["answers"].append(
                        {
                            "student_id": student,
                            "attempt": 1,
                            "status": "graded",
                            "grade": profile_grade(student, str(lesson["lesson_id"])),
                            "answer_text": ANSWER_TEXTS[
                                stable_hash("hw-text", student, lesson["lesson_id"], 1)
                                % len(ANSWER_TEXTS)
                            ],
                            "teacher_comment": "",
                            "reviewer_id": lesson["teacher_id"],
                            "submitted_at": submitted,
                            "reviewed_at": _reviewed_at(submitted, lesson, student, 1),
                            "idempotency_key": answer_idempotency_key(
                                lesson["lesson_id"], student, 1
                            ),
                        }
                    )
                elif mix < GRADED_SHARE + RETURNED_SHARE:
                    submitted = _submitted_at(lesson, student, 1)
                    assignment["answers"].append(
                        {
                            "student_id": student,
                            "attempt": 1,
                            "status": "returned",
                            "grade": None,
                            "answer_text": ANSWER_TEXTS[
                                stable_hash("hw-text", student, lesson["lesson_id"], 1)
                                % len(ANSWER_TEXTS)
                            ],
                            "teacher_comment": RETURN_COMMENTS[
                                stable_hash(
                                    "hw-comment", student, lesson["lesson_id"], 1
                                )
                                % len(RETURN_COMMENTS)
                            ],
                            "reviewer_id": lesson["teacher_id"],
                            "submitted_at": submitted,
                            "reviewed_at": _reviewed_at(submitted, lesson, student, 1),
                            "idempotency_key": answer_idempotency_key(
                                lesson["lesson_id"], student, 1
                            ),
                        }
                    )
                else:
                    # Возврат с повторной попыткой: обе строки в истории;
                    # повторная сдача — через полсуток после возврата.
                    first_submitted = _submitted_at(lesson, student, 1)
                    returned_at = _reviewed_at(first_submitted, lesson, student, 1)
                    retry_submitted = returned_at + timedelta(
                        hours=6
                        + stable_hash("hw-retry", student, lesson["lesson_id"], 2) % 18
                    )
                    assignment["answers"].extend(
                        [
                            {
                                "student_id": student,
                                "attempt": 1,
                                "status": "returned",
                                "grade": None,
                                "answer_text": ANSWER_TEXTS[
                                    stable_hash(
                                        "hw-text", student, lesson["lesson_id"], 1
                                    )
                                    % len(ANSWER_TEXTS)
                                ],
                                "teacher_comment": RETURN_COMMENTS[
                                    stable_hash(
                                        "hw-comment", student, lesson["lesson_id"], 1
                                    )
                                    % len(RETURN_COMMENTS)
                                ],
                                "reviewer_id": lesson["teacher_id"],
                                "submitted_at": first_submitted,
                                "reviewed_at": returned_at,
                                "idempotency_key": answer_idempotency_key(
                                    lesson["lesson_id"], student, 1
                                ),
                            },
                            {
                                "student_id": student,
                                "attempt": 2,
                                "status": "graded",
                                "grade": profile_grade(student, lesson["lesson_id"]),
                                "answer_text": ANSWER_TEXTS[
                                    stable_hash(
                                        "hw-text", student, lesson["lesson_id"], 2
                                    )
                                    % len(ANSWER_TEXTS)
                                ],
                                "teacher_comment": "",
                                "reviewer_id": lesson["teacher_id"],
                                "submitted_at": retry_submitted,
                                "reviewed_at": _reviewed_at(
                                    retry_submitted, lesson, student, 2
                                ),
                                "idempotency_key": answer_idempotency_key(
                                    lesson["lesson_id"], student, 2
                                ),
                            },
                        ]
                    )
            planned.append(assignment)
    report["assignments_planned"] = len(planned)
    report["answers_planned"] = sum(
        len(assignment["answers"]) for assignment in planned
    )
    return planned, report


def finish_answers(assignment: dict, homework_id: int) -> list[dict]:
    """Computes the request hashes now that the homework id is known."""
    return [
        {
            **answer,
            "homework_id": homework_id,
            "request_hash": request_fingerprint(
                homework_id, answer["student_id"], answer["answer_text"]
            ),
        }
        for answer in assignment["answers"]
    ]


# ------------------------------------------------- container bindings


class SqlHomeworkStore:
    """All generate SQL of the tool against one open session.

    The service rows are imported on construction: the module stays
    importable outside the homework container (unit tests run without
    SQLAlchemy and drive the runs with fakes).
    """

    def __init__(self, session) -> None:
        from homework_service.infrastructure.models.homework import HomeworkRow
        from homework_service.infrastructure.models.homework_answer import (
            HomeworkAnswerRow,
        )

        self._session = session
        self._homework_row = HomeworkRow
        self._answer_row = HomeworkAnswerRow

    async def existing_homework_lessons(self, lesson_ids) -> set[int]:
        """Lessons of the export that already carry an assignment."""
        from sqlalchemy import select

        found: set[int] = set()
        for batch in in_batches(lesson_ids):
            found.update(
                (
                    await self._session.scalars(
                        select(self._homework_row.issued_lesson_id).where(
                            self._homework_row.issued_lesson_id.in_(batch)
                        )
                    )
                ).all()
            )
        return found

    async def insert_homework(self, assignment: dict) -> int:
        """Inserts one assignment and its answers; returns the id."""
        lesson = assignment["lesson"]
        due_lesson = assignment["due_lesson"]
        row = self._homework_row(
            issued_lesson_id=lesson["lesson_id"],
            class_id=lesson["class_id"],
            subject_id=lesson["subject_id"],
            author_id=UUID(lesson["teacher_id"]),
            description=assignment["description"],
            due_lesson_id=due_lesson["lesson_id"] if due_lesson else None,
            manual_due_datetime=(
                None if due_lesson else lesson["starts_at"] + timedelta(days=3)
            ),
            created_at=lesson["starts_at"],
        )
        self._session.add(row)
        await self._session.flush()
        for answer in finish_answers(assignment, row.id):
            self._session.add(
                self._answer_row(
                    homework_id=row.id,
                    student_id=UUID(answer["student_id"]),
                    answer_text=answer["answer_text"],
                    idempotency_key=answer["idempotency_key"],
                    request_hash=answer["request_hash"],
                    attempt_number=answer["attempt"],
                    status=answer["status"],
                    submitted_at=answer["submitted_at"],
                    grade=answer["grade"],
                    teacher_comment=answer["teacher_comment"],
                    reviewer_id=(
                        UUID(answer["reviewer_id"]) if answer["reviewer_id"] else None
                    ),
                    reviewed_at=answer["reviewed_at"],
                )
            )
        await self._session.flush()
        return row.id


async def run_generate(
    store_factory, session_factory, export: dict, manifest: dict, rosters: dict
) -> dict:
    """Plans the walk and inserts the homework in chunk transactions."""
    check_calendar_version(export, manifest)
    lessons = parse_lessons(export["lessons"])
    cutoff = date.fromisoformat(export["cutoff"])
    class_ids = manifest_class_ids(manifest)
    if not class_ids:
        raise ValueError("The manifest carries no demo classes")
    parsed_rosters = {
        int(class_id): [str(student) for student in students]
        for class_id, students in rosters.items()
    }
    foreign = {
        lesson["class_id"] for lesson in lessons if lesson["class_id"] not in class_ids
    }
    if foreign:
        raise ValueError(
            f"Export lessons outside the manifest classes: {sorted(foreign)}"
        )
    missing_rosters = class_ids - set(parsed_rosters)
    if missing_rosters:
        raise ValueError(
            f"Rosters are missing for the manifest classes: {sorted(missing_rosters)}"
        )

    async with session_factory() as session:
        store = store_factory(session)
        existing = await store.existing_homework_lessons(
            [lesson["lesson_id"] for lesson in lessons]
        )
    planned, report = plan_homework(lessons, parsed_rosters, existing, cutoff)

    inserted_assignments = 0
    inserted_answers = 0
    chunks_inserted = 0
    failed_chunk: dict | None = None
    remaining = 0
    for start in range(0, len(planned), CHUNK_HOMEWORK):
        chunk = planned[start : start + CHUNK_HOMEWORK]
        try:
            async with session_factory() as session, session.begin():
                store = store_factory(session)
                for assignment in chunk:
                    await store.insert_homework(assignment)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            failed_chunk = {"index": chunks_inserted, "error": str(error)}
            remaining = len(planned) - start
            break
        inserted_assignments += len(chunk)
        inserted_answers += sum(len(item["answers"]) for item in chunk)
        chunks_inserted += 1
    return {
        **report,
        "cutoff": cutoff.isoformat(),
        "assignments_inserted": inserted_assignments,
        "answers_inserted": inserted_answers,
        "chunks_inserted": chunks_inserted,
        "failed_chunk": failed_chunk,
        "remaining_assignments": remaining,
    }


async def main():
    from homework_service.config import HomeworkSettings
    from homework_service.infrastructure.database import (
        create_engine,
        create_session_factory,
    )

    data = json.load(sys.stdin)
    engine = create_engine(HomeworkSettings().database_url)
    sessions = create_session_factory(engine)
    try:
        if data["mode"] != "generate":
            raise SystemExit(f"Unsupported mode: {data['mode']!r}")
        result = await run_generate(
            SqlHomeworkStore,
            sessions,
            data["export"],
            data["manifest"],
            data["rosters"],
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
