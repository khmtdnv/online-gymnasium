"""Unit tests for tools/balance_demo_homework_history_db.py.

Pure walk tests over the same synthetic lesson stream as the diary
generator; the container run is driven with fakes (no real database).
"""

import hashlib
import importlib.util
import json
import re
import sys
import unittest
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parent)
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_TOOLS_DIR, _SCHEDULE_SRC):
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


history = load_module("balance_demo_homework_history_db.py")

from schedule_service.domain import school_calendar

TEACHER = "11111111-1111-1111-1111-111111111111"
CLASSES = (101, 102)
SUBJECTS = (1, 2)


def student_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


ROSTERS = {
    class_id: [student_id(class_id * 10 + i) for i in range(1, 6)]
    for class_id in CLASSES
}


def fixture_lessons() -> list[dict]:
    """Ten study weeks: subject 1 on Mon/Wed/Fri, subject 2 on Tue/Thu."""
    days = [day for day in school_calendar.school_days() if day <= date(2026, 11, 13)]
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


def plan(existing=(), lessons=None, cutoff=CUTOFF):
    return history.plan_homework(lessons or LESSONS, ROSTERS, set(existing), cutoff)


def api_fingerprint(answer):
    """Независимая копия вычисления отпечатка команды отправки ответа."""
    payload = {
        "answer_text": answer["answer_text"],
        "files": [],
        "homework_id": answer["homework_id"],
        "student_id": answer["student_id"],
    }
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


class FakeDatabase:
    """In-memory homework state with snapshot rollback."""

    def __init__(self):
        self.homework = []
        self.answers = []
        self.tx_log = []

    def snapshot(self):
        return (list(self.homework), list(self.answers))

    def restore(self, state):
        self.homework, self.answers = state


class FakeSession:
    def __init__(self, db):
        self.db = db

    def begin(self):
        return FakeTransaction(self.db)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeTransaction:
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


class FakeHomeworkStore:
    def __init__(self, db, fail_chunks=0):
        self.db = db
        self.fail_chunks = fail_chunks
        self.next_id = 1

    async def existing_homework_lessons(self, lesson_ids):
        return {row["issued_lesson_id"] for row in self.db.homework}

    async def insert_homework(self, assignment):
        if self.fail_chunks > 0:
            self.fail_chunks -= 1
            raise RuntimeError("homework conflict")
        homework_id = self.next_id
        self.next_id += 1
        lesson = assignment["lesson"]
        due_lesson = assignment["due_lesson"]
        self.db.homework.append(
            {
                "id": homework_id,
                "issued_lesson_id": lesson["lesson_id"],
                "class_id": lesson["class_id"],
                "subject_id": lesson["subject_id"],
                "author_id": lesson["teacher_id"],
                "description": assignment["description"],
                "due_lesson_id": due_lesson["lesson_id"] if due_lesson else None,
                "manual_due_datetime": (
                    None if due_lesson else lesson["starts_at"] + timedelta(days=3)
                ),
                "created_at": lesson["starts_at"],
            }
        )
        for answer in history.finish_answers(assignment, homework_id):
            self.db.answers.append(answer)
        return homework_id


class PlanTest(unittest.TestCase):
    def test_issued_on_every_fifth_lesson_with_hash_shift(self):
        planned, report = plan()
        self.assertGreater(report["assignments_planned"], 0)
        by_subject = {}
        for lesson in LESSONS:
            by_subject.setdefault(
                (lesson["class_id"], lesson["subject_id"]), []
            ).append(lesson)
        issued_by_subject = {}
        for (class_id, subject_id), stream in by_subject.items():
            period = history.homework_period(class_id, subject_id)
            self.assertIn(
                period, (history.HOMEWORK_PERIOD - 1, history.HOMEWORK_PERIOD)
            )
            indexes = [
                index
                for index, lesson in enumerate(stream, start=1)
                if any(
                    item["lesson"]["lesson_id"] == lesson["lesson_id"]
                    for item in planned
                )
            ]
            issued_by_subject[(class_id, subject_id)] = indexes
            for index in indexes:
                self.assertEqual(index % period, 0)
            gaps = [second - first for first, second in pairwise(indexes)]
            if gaps:
                self.assertEqual(gaps, [period] * len(gaps))

    def test_due_is_next_lesson_or_manual_three_days(self):
        planned, _report = plan()
        by_subject = {}
        for lesson in LESSONS:
            by_subject.setdefault(
                (lesson["class_id"], lesson["subject_id"]), []
            ).append(lesson)
        manual = 0
        for assignment in planned:
            lesson = assignment["lesson"]
            stream = by_subject[(lesson["class_id"], lesson["subject_id"])]
            index = next(
                i
                for i, item in enumerate(stream, start=1)
                if item["lesson_id"] == lesson["lesson_id"]
            )
            if index < len(stream):
                self.assertEqual(
                    assignment["due_lesson"]["lesson_id"], stream[index]["lesson_id"]
                )
            else:
                manual += 1
        self.assertGreater(manual, 0)

    def test_answer_invariants_hold(self):
        planned, _report = plan()
        self.assertGreater(report_answer_count(planned), 0)
        statuses = set()
        for assignment in planned:
            lesson = assignment["lesson"]
            answers = history.finish_answers(assignment, 900001)
            by_student = {}
            for answer in answers:
                statuses.add(answer["status"])
                self.assertIn(answer["status"], ("submitted", "returned", "graded"))
                # Ключ и отпечаток — как у публичного API.
                self.assertIsNotNone(
                    re.fullmatch(r"[!-~]{1,128}", answer["idempotency_key"])
                )
                self.assertRegex(answer["request_hash"], r"^[0-9a-f]{64}$")
                self.assertEqual(answer["request_hash"], api_fingerprint(answer))
                # Времена: сдача после урока, проверка после сдачи.
                self.assertGreater(answer["submitted_at"], lesson["starts_at"])
                if answer["reviewed_at"] is not None:
                    self.assertGreater(answer["reviewed_at"], answer["submitted_at"])
                # CHECK-инварианты статусов.
                if answer["status"] == "submitted":
                    self.assertIsNone(answer["grade"])
                    self.assertIsNone(answer["reviewer_id"])
                    self.assertIsNone(answer["reviewed_at"])
                    self.assertEqual(answer["teacher_comment"], "")
                elif answer["status"] == "returned":
                    self.assertIsNone(answer["grade"])
                    self.assertIsNotNone(answer["reviewer_id"])
                    self.assertIsNotNone(answer["reviewed_at"])
                    self.assertTrue(answer["teacher_comment"].strip())
                else:
                    self.assertIn(answer["grade"], (2, 3, 4, 5))
                    self.assertIsNotNone(answer["reviewer_id"])
                    self.assertIsNotNone(answer["reviewed_at"])
                by_student.setdefault(answer["student_id"], []).append(answer)
            # Повторная попытка только после возврата, позже его проверки.
            for rows in by_student.values():
                rows.sort(key=lambda row: row["attempt"])
                for previous, current in pairwise(rows):
                    self.assertEqual(previous["status"], "returned")
                    self.assertEqual(current["attempt"], previous["attempt"] + 1)
                    self.assertGreater(current["submitted_at"], previous["reviewed_at"])
        # Все сценарии витрины с полным циклом представлены.
        self.assertTrue({"returned", "graded"} <= statuses)

    def test_full_cycle_only_after_due_and_future_due_submits(self):
        # Мини-поток одного предмета с принудительным периодом 5:
        # выдача на 5-м уроке. Срок после среза — только сдача без проверки.
        saved_period = history.homework_period
        history.homework_period = lambda class_id, subject_id: 5
        try:
            days = school_calendar.school_days()[:6]
            lessons = [
                {
                    "lesson_id": 6000 + index,
                    "class_id": 101,
                    "subject_id": 1,
                    "teacher_id": TEACHER,
                    "date": day,
                    "starts_at": datetime.combine(day, datetime.min.time())
                    + timedelta(hours=4),
                    "status": "planned",
                }
                for index, day in enumerate(days)
            ]
            # Срез между 5-м и 6-м уроком: выдача на 5-м, следующего урока
            # в окне нет — ручной срок впереди, только сдача без проверки.
            planned, _report = plan(lessons=lessons, cutoff=days[4])
            self.assertEqual(len(planned), 1)
            self.assertIsNone(planned[0]["due_lesson"])
            statuses = {a["status"] for a in planned[0]["answers"]}
            self.assertEqual(statuses, {"submitted"})
            # Срез после 6-го урока: полный цикл — проверенные и возвращённые.
            planned_full, _report = plan(lessons=lessons, cutoff=days[5])
            full_statuses = {
                answer["status"]
                for assignment in planned_full
                for answer in assignment["answers"]
            }
            self.assertTrue({"returned", "graded"} <= full_statuses)
        finally:
            history.homework_period = saved_period

    def test_rerun_skips_lessons_with_existing_homework(self):
        planned, report = plan()
        existing = {item["lesson"]["lesson_id"] for item in planned}
        again, again_report = plan(existing)
        self.assertEqual(again, [])
        self.assertEqual(
            again_report["assignments_skipped_existing"], report["assignments_planned"]
        )

    def test_grades_match_the_diary_profile(self):
        diary = load_module("balance_demo_diary_db.py")
        planned, _report = plan()
        checked = 0
        for assignment in planned:
            lesson = assignment["lesson"]
            for answer in assignment["answers"]:
                if answer["status"] != "graded":
                    continue
                self.assertEqual(
                    answer["grade"],
                    diary.profile_grade(answer["student_id"], str(lesson["lesson_id"])),
                )
                checked += 1
        self.assertGreater(checked, 0)

    def test_constants(self):
        self.assertEqual(history.HOMEWORK_PERIOD, 5)
        self.assertEqual(history.CHUNK_HOMEWORK, 200)
        self.assertEqual(history.SQL_BATCH_SIZE, 1000)
        self.assertEqual(
            history.GRADED_SHARE
            + history.RETURNED_SHARE
            + history.RETURN_REGRADED_SHARE
            + history.SUBMITTED_SHARE,
            90,
        )


def report_answer_count(planned):
    return sum(len(assignment["answers"]) for assignment in planned)


class GuardsTest(unittest.TestCase):
    def test_calendar_version_guard(self):
        export_ok = {"calendar_version": 3}
        manifest_ok = {"year_fingerprint": {"calendar_version": 3}}
        history.check_calendar_version(export_ok, manifest_ok)
        with self.assertRaises(ValueError):
            history.check_calendar_version(
                {"calendar_version": 3}, {"year_fingerprint": {"calendar_version": 4}}
            )
        with self.assertRaises(ValueError):
            history.check_calendar_version({}, manifest_ok)


class RunTest(unittest.TestCase):
    def export_of(self, lessons):
        return {
            "cutoff": CUTOFF.isoformat(),
            "calendar_version": 3,
            "lessons": [
                {
                    **lesson,
                    "date": lesson["date"].isoformat(),
                    "starts_at": lesson["starts_at"].isoformat(),
                }
                for lesson in lessons
            ],
        }

    def manifest_of(self, calendar_version=3):
        return {
            "classes": [{"id": class_id} for class_id in CLASSES],
            "year_fingerprint": {"calendar_version": calendar_version},
        }

    def test_generate_inserts_and_reports(self):
        import asyncio

        db = FakeDatabase()
        store = FakeHomeworkStore(db)
        result = asyncio.run(
            history.run_generate(
                lambda session=None: store,
                lambda: FakeSession(db),
                self.export_of(LESSONS),
                self.manifest_of(),
                ROSTERS,
            )
        )
        self.assertEqual(result["assignments_inserted"], len(db.homework))
        self.assertEqual(result["answers_inserted"], len(db.answers))
        self.assertIsNone(result["failed_chunk"])
        self.assertEqual(db.tx_log.count("commit"), result["chunks_inserted"])

    def test_generate_failure_rolls_back_and_reports_remaining(self):
        import asyncio

        db = FakeDatabase()
        store = FakeHomeworkStore(db, fail_chunks=1)
        saved = history.CHUNK_HOMEWORK
        history.CHUNK_HOMEWORK = 1
        try:
            result = asyncio.run(
                history.run_generate(
                    lambda session=None: store,
                    lambda: FakeSession(db),
                    self.export_of(LESSONS),
                    self.manifest_of(),
                    ROSTERS,
                )
            )
        finally:
            history.CHUNK_HOMEWORK = saved
        self.assertIsNotNone(result["failed_chunk"])
        self.assertGreater(result["remaining_assignments"], 0)
        self.assertEqual(db.homework, [])
        self.assertEqual(db.tx_log, ["rollback"])

    def test_missing_rosters_refuse(self):
        import asyncio

        db = FakeDatabase()
        store = FakeHomeworkStore(db)
        rosters = {CLASSES[0]: [student_id(1)]}
        with self.assertRaises(ValueError):
            asyncio.run(
                history.run_generate(
                    lambda session=None: store,
                    lambda: FakeSession(db),
                    self.export_of(LESSONS),
                    self.manifest_of(),
                    rosters,
                )
            )


if __name__ == "__main__":
    unittest.main()
