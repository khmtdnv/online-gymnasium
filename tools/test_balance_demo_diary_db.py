"""Unit tests for tools/balance_demo_diary_db.py.

Pure walk tests over a synthetic lesson stream of the real 2026/27
calendar; the container runs are driven with fakes (no real database).
"""

import importlib.util
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parent)
_JOURNAL_SRC = str(Path(__file__).resolve().parents[1] / "services" / "journal" / "src")
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_TOOLS_DIR, _JOURNAL_SRC, _SCHEDULE_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def load_module(name: str):
    """Loads a module from tools without package installation."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


diary = load_module("balance_demo_diary_db.py")

from journal_service.domain import study_quarters
from schedule_service.domain import school_calendar

TEACHER = "11111111-1111-1111-1111-111111111111"
CLASSES = (101, 102)
SUBJECTS = (1, 2)
QUARTERS = [tuple(bounds) for bounds in study_quarters.QUARTERS]
YEAR_START, YEAR_END = study_quarters.STUDY_YEAR
WEEKS = 6


def student_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


ROSTERS = {
    class_id: [student_id(class_id * 10 + i) for i in range(1, 6)]
    for class_id in CLASSES
}


def fixture_lessons() -> list[dict]:
    """Six study weeks: subject 1 on Mon/Wed/Fri, subject 2 on Tue/Thu."""
    days = [day for day in school_calendar.school_days() if day <= date(2026, 10, 16)]
    lessons = []
    lesson_id = 5000
    for class_id in CLASSES:
        for day in days:
            for period, subject_id in ((1, 1), (2, 2)):
                weekday = day.weekday()
                if (subject_id == 1 and weekday not in (0, 2, 4)) or (
                    subject_id == 2 and weekday not in (1, 3)
                ):
                    continue
                lesson_id += 1
                starts_at = datetime.combine(day, datetime.min.time()) + timedelta(
                    hours=4 + period
                )
                lessons.append(
                    {
                        "lesson_id": lesson_id,
                        "class_id": class_id,
                        "subject_id": subject_id,
                        "teacher_id": TEACHER,
                        "date": day,
                        "starts_at": starts_at,
                        "status": "planned",
                    }
                )
    lessons.sort(key=lambda row: (row["starts_at"], row["lesson_id"]))
    return lessons


LESSONS = fixture_lessons()
CUTOFF = max(lesson["date"] for lesson in LESSONS)


def plan(existing_attendance=(), existing_grades=(), lessons=None, cutoff=CUTOFF):
    return diary.plan_diary(
        lessons or LESSONS,
        ROSTERS,
        list(existing_attendance),
        list(existing_grades),
        cutoff,
        QUARTERS,
        YEAR_START,
        YEAR_END,
    )


class FakeDatabase:
    """In-memory attendance/grades state with snapshot rollback."""

    def __init__(self, rosters):
        self.rosters = {
            class_id: list(students) for class_id, students in rosters.items()
        }
        self.attendance = []
        self.grades = []
        self.tx_log = []

    def snapshot(self):
        return (list(self.attendance), list(self.grades))

    def restore(self, state):
        self.attendance, self.grades = state


class FakeSession:
    """Async session with real-transaction semantics over FakeDatabase."""

    def __init__(self, db):
        self.db = db

    def begin(self):
        return FakeTransaction(self.db)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeTransaction:
    """Commits on clean exit, restores the snapshot on an error."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self._state = self.db.snapshot()
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is not None:
            self.db.tx_log.append("rollback")
            self.db.restore(self._state)
        else:
            self.db.tx_log.append("commit")
        return False


class FakeDiaryStore:
    """The store interface of the tool over FakeDatabase."""

    def __init__(self, db, fail_chunks=0):
        self.db = db
        self.fail_chunks = fail_chunks

    async def rosters_of_classes(self, class_ids):
        return {
            class_id: list(students)
            for class_id, students in self.db.rosters.items()
            if class_id in set(class_ids)
        }

    async def existing_rows(self, lesson_ids):
        return self.db.attendance, self.db.grades

    async def insert_attendance(self, rows):
        if self.fail_chunks > 0:
            self.fail_chunks -= 1
            raise RuntimeError("journal conflict")
        self.db.attendance.extend(
            (row["lesson_id"], row["student_id"], row["status"]) for row in rows
        )

    async def insert_grades(self, rows):
        self.db.grades.extend(
            (row["lesson_id"], row["student_id"], row["kind"]) for row in rows
        )

    async def delete_generator_rows(self):
        attendance = len(self.db.attendance)
        grades = len(self.db.grades)
        self.db.attendance = []
        self.db.grades = []
        return attendance, grades


def fake_factories(db):
    sessions = FakeSessionFactory(db)
    return lambda session=None: FakeDiaryStore(db), sessions


class FakeSessionFactory:
    """Yields FakeSession objects sharing one FakeDatabase."""

    def __init__(self, db):
        self.db = db

    def __call__(self):
        return FakeSession(self.db)


class PlanTest(unittest.TestCase):
    def test_density_guarantee_and_statuses(self):
        attendance, grades, report = plan()
        self.assertEqual(report["lessons_written"], len(LESSONS))
        self.assertGreater(report["attendance_rows"], 0)
        # Посещаемость: каждому ученику урока — ровно одна строка.
        seen = set()
        for row in attendance:
            key = (row["lesson_id"], row["student_id"])
            self.assertNotIn(key, seen)
            seen.add(key)
            self.assertIn(
                row["status"],
                ("present", "absent_sick", "absent_excused", "absent_unexcused"),
            )
        per_lesson = {}
        for row in attendance:
            per_lesson.setdefault(row["lesson_id"], []).append(row["student_id"])
        for lesson in LESSONS:
            self.assertEqual(
                sorted(per_lesson[lesson["lesson_id"]]),
                sorted(ROSTERS[lesson["class_id"]]),
            )
        # Оценки только присутствовавшим, значения из профиля ученика.
        status_by_key = {
            (row["lesson_id"], row["student_id"]): row["status"] for row in attendance
        }
        for row in grades:
            self.assertEqual(
                status_by_key[(row["lesson_id"], row["student_id"])], "present"
            )
            self.assertIn(row["grade"], (2, 3, 4, 5))
            self.assertIn(row["kind"], ("oral", "written", "control"))
            expected = diary.profile_grade(row["student_id"], str(row["lesson_id"]))
            self.assertEqual(row["grade"], expected)
        # Плотность 2–4 оценки в неделю суммарно на ученика.
        week_counts = {}
        for row in grades:
            week = row["lesson_date"] - timedelta(days=row["lesson_date"].weekday())
            week_counts[(row["student_id"], week)] = (
                week_counts.get((row["student_id"], week), 0) + 1
            )
        present_per_week = {}
        for row in attendance:
            if row["status"] != "present":
                continue
            week = row["lesson_date"] - timedelta(days=row["lesson_date"].weekday())
            present_per_week.setdefault((row["student_id"], week), 0)
            present_per_week[(row["student_id"], week)] += 1
        for key, count in week_counts.items():
            self.assertLessEqual(count, diary.WEEKLY_MAX, key)
        for key, present in present_per_week.items():
            if present >= 2:
                self.assertIn(
                    week_counts.get(key, 0),
                    range(diary.WEEKLY_MIN, diary.WEEKLY_MAX + 1),
                    key,
                )
        # Гарантия: хотя бы одна оценка по каждому предмету за четверть.
        subject_seen = set()
        for row in grades:
            subject_seen.add((row["student_id"], row["subject_id"]))
        for class_id in CLASSES:
            for student in ROSTERS[class_id]:
                for subject_id in SUBJECTS:
                    self.assertIn((student, subject_id), subject_seen)
        # Контрольные: периодические, классу, тип control.
        control_rows = [row for row in grades if row["kind"] == "control"]
        self.assertTrue(control_rows)
        counter = {}
        control_ids = set()
        for lesson in LESSONS:
            key = (lesson["class_id"], lesson["subject_id"])
            counter[key] = counter.get(key, 0) + 1
            if counter[key] % diary.CONTROL_PERIOD == 0:
                control_ids.add(lesson["lesson_id"])
        self.assertTrue(control_rows[0]["lesson_id"] in control_ids)

    def test_rerun_without_cutoff_movement_inserts_nothing(self):
        attendance, grades, _report = plan()
        existing_attendance = [
            (row["lesson_id"], row["student_id"], row["status"]) for row in attendance
        ]
        existing_grades = [
            (row["lesson_id"], row["student_id"], row["kind"]) for row in grades
        ]
        again_attendance, again_grades, report = plan(
            existing_attendance, existing_grades
        )
        self.assertEqual(again_attendance, [])
        self.assertEqual(again_grades, [])
        self.assertEqual(report["lessons_with_rows"], len(LESSONS))
        self.assertEqual(report["lessons_written"], 0)

    def test_extension_appends_only_new_lessons(self):
        attendance, grades, _report = plan()
        existing_attendance = [
            (row["lesson_id"], row["student_id"], row["status"]) for row in attendance
        ]
        existing_grades = [
            (row["lesson_id"], row["student_id"], row["kind"]) for row in grades
        ]
        # Продление: ещё одна учебная неделя после среза.
        extra_days = [
            day
            for day in school_calendar.school_days()
            if CUTOFF < day <= CUTOFF + timedelta(days=7)
        ]
        extended = list(LESSONS)
        lesson_id = max(lesson["lesson_id"] for lesson in LESSONS)
        for day in extra_days:
            for class_id in CLASSES:
                for period, subject_id in ((1, 1), (2, 2)):
                    weekday = day.weekday()
                    if (subject_id == 1 and weekday not in (0, 2, 4)) or (
                        subject_id == 2 and weekday not in (1, 3)
                    ):
                        continue
                    lesson_id += 1
                    starts_at = datetime.combine(day, datetime.min.time()) + timedelta(
                        hours=4 + period
                    )
                    extended.append(
                        {
                            "lesson_id": lesson_id,
                            "class_id": class_id,
                            "subject_id": subject_id,
                            "teacher_id": TEACHER,
                            "date": day,
                            "starts_at": starts_at,
                            "status": "planned",
                        }
                    )
        extended.sort(key=lambda row: (row["starts_at"], row["lesson_id"]))
        extended_cutoff = max(lesson["date"] for lesson in extended)
        new_attendance, new_grades, new_report = plan(
            existing_attendance,
            existing_grades,
            lessons=extended,
            cutoff=extended_cutoff,
        )
        self.assertEqual(new_report["lessons_with_rows"], len(LESSONS))
        written_ids = {lesson["lesson_id"] for lesson in LESSONS}
        self.assertTrue(
            all(row["lesson_id"] not in written_ids for row in new_attendance)
        )
        self.assertTrue(new_attendance and new_grades)

    def test_live_rows_block_the_lesson_forever(self):
        live_lesson = LESSONS[3]
        live_student = ROSTERS[live_lesson["class_id"]][0]
        attendance, _grades, report = plan(
            [(live_lesson["lesson_id"], live_student, "present")]
        )
        self.assertEqual(report["lessons_written"], len(LESSONS) - 1)
        self.assertEqual(report["lessons_with_rows"], 1)
        for row in attendance:
            self.assertNotEqual(row["lesson_id"], live_lesson["lesson_id"])

    def test_not_planned_and_after_cutoff_lessons_are_skipped(self):
        lessons = [
            {**LESSONS[0], "status": "canceled"},
            *LESSONS[1:],
        ]
        attendance, _grades, report = plan(lessons=lessons)
        self.assertEqual(report["lessons_not_planned"], 1)
        self.assertEqual(report["lessons_written"], len(LESSONS) - 1)
        attendance, _grades, report = plan(
            lessons=LESSONS, cutoff=LESSONS[2]["date"] - timedelta(days=1)
        )
        self.assertEqual(report["lessons_after_cutoff"], len(LESSONS) - 2)
        self.assertEqual(report["lessons_written"], 2)
        cutoff_day = LESSONS[2]["date"] - timedelta(days=1)
        for row in attendance:
            self.assertLessEqual(row["lesson_date"], cutoff_day)

    def test_absence_episodes_cover_reasons_and_weekdays(self):
        reasons = set()
        for index in range(1, 200):
            student = student_id(index)
            episodes = diary.absence_episode_dates(student, YEAR_START, YEAR_END)
            count = 0
            for day, status in episodes.items():
                self.assertNotEqual(day.weekday(), 6)
                reasons.add(status)
                count += 1
            self.assertGreaterEqual(count, diary.ABSENCE_EPISODES_MIN)
            self.assertLessEqual(
                count,
                diary.ABSENCE_EPISODES_MAX * 2,
            )
        self.assertEqual(reasons, {"absent_sick", "absent_excused", "absent_unexcused"})

    def test_constants_of_the_specification(self):
        self.assertEqual((diary.WEEKLY_MIN, diary.WEEKLY_MAX), (2, 4))
        self.assertEqual(diary.CONTROL_PERIOD, 12)
        self.assertEqual(diary.GUARANTEE_MAX, 4)
        self.assertEqual(
            (diary.ABSENCE_EPISODES_MIN, diary.ABSENCE_EPISODES_MAX), (2, 3)
        )
        self.assertEqual(diary.CHUNK_LESSONS, 500)
        self.assertEqual(diary.SQL_BATCH_SIZE, 1000)


class RunTest(unittest.TestCase):
    def run_generate(self, db, export, manifest, store=None):
        import asyncio

        store_factory, sessions = fake_factories(db)
        if store is not None:
            store_factory = lambda session=None: store
        return asyncio.run(
            diary.run_generate(
                store_factory,
                sessions,
                export,
                manifest,
                QUARTERS,
                (YEAR_START, YEAR_END),
            )
        )

    def export_of(self, lessons):
        return {
            "cutoff": CUTOFF.isoformat(),
            "calendar_version": study_quarters.CALENDAR_VERSION,
            "lessons": [
                {
                    **lesson,
                    "date": lesson["date"].isoformat(),
                    "starts_at": lesson["starts_at"].isoformat(),
                }
                for lesson in lessons
            ],
        }

    def manifest_of(self, calendar_version=study_quarters.CALENDAR_VERSION):
        return {
            "classes": [{"id": class_id} for class_id in CLASSES],
            "year_fingerprint": {"calendar_version": calendar_version},
        }

    def test_generate_writes_chunks_and_reports_rosters(self):
        db = FakeDatabase(ROSTERS)
        result = self.run_generate(db, self.export_of(LESSONS), self.manifest_of())
        self.assertEqual(result["attendance_inserted"], len(db.attendance))
        self.assertEqual(result["grades_inserted"], len(db.grades))
        self.assertEqual(result["chunks_inserted"], 1)
        self.assertIsNone(result["failed_chunk"])
        self.assertEqual(
            result["rosters"],
            {str(class_id): ROSTERS[class_id] for class_id in CLASSES},
        )
        self.assertEqual(db.tx_log.count("commit"), 1)

    def test_generate_failure_rolls_back_and_reports_remaining(self):
        db = FakeDatabase(ROSTERS)
        store = FakeDiaryStore(db, fail_chunks=1)
        saved = diary.CHUNK_LESSONS
        diary.CHUNK_LESSONS = 1
        try:
            result = self.run_generate(
                db, self.export_of(LESSONS), self.manifest_of(), store=store
            )
        finally:
            diary.CHUNK_LESSONS = saved
        self.assertIsNotNone(result["failed_chunk"])
        self.assertGreater(result["remaining_lessons"], 0)
        self.assertEqual(db.attendance, [])
        self.assertEqual(db.tx_log, ["rollback"])

    def test_wipe_deletes_generator_rows(self):
        import asyncio

        db = FakeDatabase(ROSTERS)
        db.attendance = [(1, "s", "present")]
        db.grades = [(1, "s", "oral")]
        store_factory, sessions = fake_factories(db)
        result = asyncio.run(diary.run_wipe(store_factory, sessions))
        self.assertEqual(result, {"attendance_deleted": 1, "grades_deleted": 1})
        self.assertEqual((db.attendance, db.grades), ([], []))


class GuardsTest(unittest.TestCase):
    def test_calendar_version_mismatch_refuses(self):
        with self.assertRaises(ValueError):
            diary.check_calendar_version(
                {"year_fingerprint": {"calendar_version": 2}},
                study_quarters.CALENDAR_VERSION,
            )
        with self.assertRaises(ValueError):
            diary.check_calendar_version({}, study_quarters.CALENDAR_VERSION)
        diary.check_calendar_version(
            {"year_fingerprint": {"calendar_version": study_quarters.CALENDAR_VERSION}},
            study_quarters.CALENDAR_VERSION,
        )

    def test_quarter_number_uses_quarter_bounds(self):
        self.assertEqual(diary.quarter_number(date(2026, 9, 1), QUARTERS), 1)
        self.assertEqual(diary.quarter_number(date(2026, 10, 30), QUARTERS), 1)
        self.assertEqual(diary.quarter_number(date(2026, 11, 9), QUARTERS), 2)
        with self.assertRaises(ValueError):
            diary.quarter_number(date(2026, 10, 31), QUARTERS)


class LessonSchoolDateCompatTest(unittest.TestCase):
    """Совместимость пары «дневник-ДЗ»: один и тот же профиль ученика."""

    def test_profile_matches_the_homework_generator(self):
        homework = load_module("balance_demo_homework_history_db.py")
        for index in range(1, 50):
            student = student_id(index)
            self.assertEqual(
                diary.profile_level(student), homework.profile_level(student)
            )
            self.assertEqual(
                diary.profile_grade(student, "7"),
                homework.profile_grade(student, "7"),
            )


if __name__ == "__main__":
    unittest.main()
