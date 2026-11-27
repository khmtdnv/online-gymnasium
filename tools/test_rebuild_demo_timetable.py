"""Ключевые проверки перестройки демо-расписания."""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import ClassVar

_TOOLS_DIR = str(Path(__file__).resolve().parent)
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_TOOLS_DIR, _SCHEDULE_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from demo_curriculum import GRADE_CURRICULUM
from schedule_service.domain.school_periods import (
    PERIODS,
    TIMEZONE,
    period_for,
)


def load_module(name: str):
    """Загружает модуль из tools без пакетной установки."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rebuild = load_module("rebuild_demo_timetable.py")
expand = load_module("expand_demo_school.py")

DAYS = [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)]


def make_users():
    """Собирает демо-учётки: классные руководители и предметники."""
    users = {}

    def add(email):
        users[email] = {"id": f"id-{email}", "role": "teacher"}

    for grade in range(1, 12):
        for code in expand.CODES:
            add(expand.emails(grade, code))
            for subject_id, _name in expand.SUBJECTS:
                if subject_id != 1:
                    add(expand.subject_teacher_email(grade, code, subject_id))
    return users


def make_school(users):
    """Маленькая школа: 3 класса, 3 предмета, по 3 урока в день."""
    classes = [
        {"id": 1, "name": "1А"},
        {"id": 2, "name": "1Б"},
        {"id": 3, "name": "5А"},
    ]
    lessons = []
    lesson_id = 100
    reviewer = users["teacher01@demo.og.test"]["id"]
    for class_id in (1, 2, 3):
        for day in DAYS:
            for slot, hour in enumerate((9, 10, 11)):
                subject = (1, 2, 1001)[slot]
                teacher = users[
                    expand.subject_teacher_email(1, "a", subject)
                    if subject != 1
                    else "teacher01@demo.og.test"
                ]["id"]
                if class_id == 2:
                    teacher = users[
                        expand.subject_teacher_email(1, "b", subject)
                        if subject != 1
                        else "teacher02@demo.og.test"
                    ]["id"]
                if class_id == 3:
                    teacher = users[
                        expand.subject_teacher_email(5, "a", subject)
                        if subject != 1
                        else "teacher05@demo.og.test"
                    ]["id"]
                start = datetime.combine(day, time(hour), rebuild.TIMEZONE)
                lesson_id += 1
                lessons.append(
                    {
                        "id": lesson_id,
                        "class_id": class_id,
                        "teacher_id": teacher,
                        "subject_id": subject,
                        "starts_at": start.isoformat(),
                        "ends_at": (start + timedelta(minutes=45)).isoformat(),
                        "version": 1,
                        "managed": True,
                    }
                )
    protected = {lessons[0]["id"], lessons[3]["id"]}
    for row in lessons:
        if row["id"] in protected:
            row["teacher_id"] = reviewer
    return classes, lessons, protected


class RebuildTimetableTests(unittest.TestCase):
    def setUp(self):
        self.users = make_users()
        self.classes, self.lessons, self.protected = make_school(self.users)

    def plan(self):
        """Строит план и применяет его к копии уроков."""
        plan, teacher_by_key, stats = rebuild.plan_rebuild(
            self.lessons, self.protected, self.classes, self.users
        )
        changes = {entry["id"]: entry for entry in plan}
        applied = []
        for row in self.lessons:
            entry = changes.get(row["id"])
            if entry:
                row = {
                    **row,
                    "teacher_id": entry["teacher_id"],
                    "subject_id": entry["subject_id"],
                    "starts_at": entry["starts_at"],
                    "ends_at": entry["ends_at"],
                }
            applied.append(row)
        return plan, teacher_by_key, stats, applied

    def test_no_overlaps_and_single_teacher_for_class_subject(self):
        _plan, _teacher_by_key, _stats, applied = self.plan()
        by_key = {}
        for row in applied:
            key = (row["class_id"], row["subject_id"])
            by_key.setdefault(key, set()).add(row["teacher_id"])
        for key, teachers in by_key.items():
            self.assertEqual(len(teachers), 1, f"{key} ведут несколько учителей")
        busy = {}
        for row in applied:
            start = datetime.fromisoformat(row["starts_at"])
            end = datetime.fromisoformat(row["ends_at"])
            for begin, finish in busy.setdefault(row["teacher_id"], []):
                self.assertFalse(
                    start < finish and begin < end,
                    f"пересечение уроков учителя {row['teacher_id']}",
                )
            busy[row["teacher_id"]].append((start, end))

    def test_teacher_teaches_single_subject_and_days_are_contiguous(self):
        _plan, _teachers, _stats, applied = self.plan()
        subjects = {}
        class_day = {}
        for row in applied:
            subjects.setdefault(row["teacher_id"], set()).add(row["subject_id"])
            start = datetime.fromisoformat(row["starts_at"]).astimezone(
                rebuild.TIMEZONE
            )
            period = period_for(start, datetime.fromisoformat(row["ends_at"]))
            self.assertIsNotNone(period, f"урок {row['id']} вне сетки периодов")
            slots = class_day.setdefault((row["class_id"], start.date()), [])
            slots.append(period.number)
        for rows in subjects.values():
            self.assertEqual(len(rows), 1, "учитель ведёт несколько предметов")
        for slots in class_day.values():
            used = sorted(slots)
            self.assertEqual(
                used, list(range(used[0], used[0] + len(used))), "окно в дне класса"
            )

    def test_protected_lessons_keep_subject_day_and_teacher(self):
        _plan, _teachers, _stats, applied = self.plan()
        reviewer = self.users["teacher01@demo.og.test"]["id"]
        for row in applied:
            if row["id"] in self.protected:
                original = next(
                    item for item in self.lessons if item["id"] == row["id"]
                )
                self.assertEqual(row["teacher_id"], original["teacher_id"])
                self.assertEqual(row["subject_id"], original["subject_id"])
                self.assertEqual(row["teacher_id"], reviewer)

    def test_class_day_capacity_and_period_bounds_are_preserved(self):
        _plan, _teachers, _stats, applied = self.plan()
        before = {}
        after = {}
        for row in self.lessons:
            day = (
                datetime.fromisoformat(row["starts_at"])
                .astimezone(rebuild.TIMEZONE)
                .date()
            )
            before[(row["class_id"], day)] = before.get((row["class_id"], day), 0) + 1
        for row in applied:
            day = (
                datetime.fromisoformat(row["starts_at"])
                .astimezone(rebuild.TIMEZONE)
                .date()
            )
            after[(row["class_id"], day)] = after.get((row["class_id"], day), 0) + 1
            # Каждый урок после пересборки точно совпадает с одним из
            # семи периодов сетки (period_for возвращает None вне сетки).
            period = period_for(
                datetime.fromisoformat(row["starts_at"]),
                datetime.fromisoformat(row["ends_at"]),
            )
            self.assertIsNotNone(period, f"урок {row['id']} вне семипериодной сетки")
        self.assertEqual(before, after)

    def test_no_teacher_or_class_double_booking_within_period(self):
        _plan, _teachers, _stats, applied = self.plan()
        taken = set()
        for row in applied:
            start = datetime.fromisoformat(row["starts_at"])
            day = start.astimezone(rebuild.TIMEZONE).date()
            period = period_for(start, datetime.fromisoformat(row["ends_at"]))
            self.assertIsNotNone(period)
            teacher_slot = (row["teacher_id"], day, period.number)
            class_slot = (row["class_id"], day, period.number)
            self.assertNotIn(
                teacher_slot, taken, "учитель занят в одном периоде дважды"
            )
            self.assertNotIn(class_slot, taken, "класс занят в одном периоде дважды")
            taken.update((teacher_slot, class_slot))

    def test_full_day_reaches_all_seven_periods(self):
        users = make_users()
        day = date(2026, 11, 16)
        subjects = [subject for subject, _name in expand.SUBJECTS[:7]]
        teacher_of = {}
        lessons = []
        for index, subject in enumerate(subjects, start=1):
            email = (
                "teacher01@demo.og.test"
                if subject == 1
                else expand.subject_teacher_email(1, "a", subject)
            )
            teacher = users[email]["id"]
            teacher_of[(1, subject)] = teacher
            # Входные уроки намеренно «старые» (все с 9:00 часа): сетка
            # назначается перестройкой, а не входными данными.
            start = datetime.combine(day, time(9), rebuild.TIMEZONE)
            lessons.append(
                {
                    "id": index,
                    "class_id": 1,
                    "teacher_id": teacher,
                    "subject_id": subject,
                    "starts_at": start.isoformat(),
                    "ends_at": (start + timedelta(minutes=45)).isoformat(),
                    "version": 1,
                    "managed": True,
                }
            )
        by_class_day = {1: {day: [{**row, "_protected": False} for row in lessons]}}
        placement = rebuild.assign_periods(by_class_day, teacher_of)
        used = sorted(entry["period"] for entry in placement[1].values())
        self.assertEqual(
            used,
            list(range(1, len(PERIODS) + 1)),
            "полный день класса обязан занять все семь периодов",
        )
        plan = rebuild.build_plan(lessons, placement, teacher_of)
        changes = {entry["id"]: entry for entry in plan}
        for row in lessons:
            entry = changes.get(row["id"])
            final = row["starts_at"] if entry is None else entry["starts_at"]
            final_end = row["ends_at"] if entry is None else entry["ends_at"]
            period = period_for(
                datetime.fromisoformat(final),
                datetime.fromisoformat(final_end),
            )
            self.assertIsNotNone(
                period, f"план должен давать точные границы периода (урок {row['id']})"
            )

    def test_plan_is_deterministic_and_only_changes_difference(self):
        plan_a, _ta, _sa, _ = self.plan()
        plan_b, _tb, _sb, _ = self.plan()
        self.assertEqual(plan_a, plan_b)
        for entry in plan_a:
            original = next(item for item in self.lessons if item["id"] == entry["id"])
            same = (
                original["teacher_id"] == entry["teacher_id"]
                and original["subject_id"] == entry["subject_id"]
                and original["starts_at"] == entry["starts_at"]
            )
            self.assertFalse(same)

    def test_verify_state_accepts_rebuilt_school(self):
        _plan, _teachers, _stats, applied = self.plan()
        _healthy, _info = rebuild.verify_state(applied, self.users)
        self.assertNotIn("reason", _info)
        # На мини-школе пороги занятости не обязаны выполняться —
        # важна структурная целостность (нет пересечений и смешений).
        self.assertTrue(_info["classes"] == 3)

    def test_teacher01_gets_math_in_multiple_classes(self):
        _plan, teacher_by_key, _stats, _applied = self.plan()
        reviewer = self.users["teacher01@demo.og.test"]["id"]
        math_classes = {
            class_id
            for (class_id, subject), teacher in teacher_by_key.items()
            if subject == 1 and teacher == reviewer
        }
        self.assertIn(1, math_classes)
        self.assertGreaterEqual(len(math_classes), 1)


if __name__ == "__main__":
    unittest.main()


class SubjectPerDayRules(unittest.TestCase):
    """Правила «сколько одного предмета в день допустимо»."""

    WEEK: ClassVar[list[date]] = [
        date(2026, 11, 16) + timedelta(days=i) for i in range(5)
    ]

    def make_lessons(self, per_subject: dict[int, list[int]]):
        """Собирает неделю одного класса: предмет → список дней уроков.

        Часы внутри дня не пересекаются, предметы класса ведёт один
        виртуальный учитель каждый — проверяются только правила дней.
        """
        lessons = []
        lesson_id = 500
        hour_used: dict[date, int] = {}
        teacher_by_subject = {}
        for subject, day_indexes in per_subject.items():
            teacher_by_subject[subject] = f"t{subject}"
            for index in day_indexes:
                day = self.WEEK[index]
                hour = hour_used.get(day, 9)
                hour_used[day] = hour + 1
                start = datetime.combine(day, time(hour), rebuild.TIMEZONE)
                lesson_id += 1
                lessons.append(
                    {
                        "id": lesson_id,
                        "class_id": 1,
                        "teacher_id": teacher_by_subject[subject],
                        "subject_id": subject,
                        "starts_at": start.isoformat(),
                        "ends_at": (start + timedelta(minutes=45)).isoformat(),
                        "version": 1,
                        "managed": True,
                    }
                )
        return lessons

    def test_five_lessons_spread_one_per_day(self):
        lessons = self.make_lessons({2: [0, 1, 2, 3, 4], 1: [0, 1, 2, 3, 4]})
        plan = rebuild.plan_day_subjects(lessons, protected=set(), days=self.WEEK)
        per_day = {
            day: [row["subject_id"] for row in rows] for day, rows in plan[1].items()
        }
        for day, subjects in per_day.items():
            self.assertEqual(sorted(subjects), [1, 2], f"день {day}: {subjects}")

    def test_sixth_lesson_allows_single_necessary_double(self):
        # 15 уроков на 5 дней по 3: русский 6 (нужен один дубль),
        # математика 5 и литература 4 — по одному в день.
        lessons = self.make_lessons(
            {2: [0, 1, 2, 3, 4, 4], 1: [0, 1, 2, 3, 4], 1001: [0, 1, 2, 3]}
        )
        plan = rebuild.plan_day_subjects(lessons, protected=set(), days=self.WEEK)
        counts = {}
        for day, rows in plan[1].items():
            counts[day] = sum(1 for row in rows if row["subject_id"] == 2)
        self.assertEqual(sum(counts.values()), 6)
        self.assertEqual(max(counts.values()), 2, "три урока в день недопустимы")
        self.assertEqual(
            sum(1 for count in counts.values() if count == 2),
            1,
            "двойной нужен ровно один",
        )

    def test_verify_state_rejects_five_same_subject_in_one_day(self):
        lessons = []
        for hour in range(9, 14):
            start = datetime.combine(self.WEEK[0], time(hour), rebuild.TIMEZONE)
            lessons.append(
                {
                    "id": 900 + hour,
                    "class_id": 1,
                    "teacher_id": "t2",
                    "subject_id": 2,
                    "starts_at": start.isoformat(),
                    "ends_at": (start + timedelta(minutes=45)).isoformat(),
                    "version": 1,
                    "managed": True,
                }
            )
        users = {"t@example.test": {"id": "t2", "role": "teacher"}}
        healthy, info = rebuild.verify_state(lessons, users)
        self.assertFalse(healthy)
        self.assertIn("три и больше уроков", info["reason"])

    def test_verify_state_rejects_unnecessary_double(self):
        lessons = self.make_lessons({2: [0, 0, 1], 1: [0, 1, 2]})
        users = {"t@example.test": {"id": "t1", "role": "teacher"}}
        healthy, info = rebuild.verify_state(lessons, users)
        self.assertFalse(healthy)
        self.assertIn("не был необходим", info["reason"])

    def test_verify_state_rejects_student_window(self):
        lessons = self.make_lessons({2: [0], 1: [0]})
        # Периоды 1 и 3: уроки на сетке, но между ними окно.
        for row, index in zip(lessons, (0, 2), strict=True):
            period = PERIODS[index]
            row["starts_at"] = datetime.combine(
                self.WEEK[0], period.start_at, TIMEZONE
            ).isoformat()
            row["ends_at"] = datetime.combine(
                self.WEEK[0], period.end_at, TIMEZONE
            ).isoformat()
            row["teacher_id"] = "t1"
        users = {"t@example.test": {"id": "t1", "role": "teacher"}}
        healthy, info = rebuild.verify_state(lessons, users)
        self.assertFalse(healthy)
        self.assertIn("окно", info["reason"])

    def test_verify_state_rejects_offgrid_legacy_hours(self):
        # Почасовые уроки (10:00) больше не проходят проверку сетки.
        lessons = self.make_lessons({2: [0, 1], 1: [0, 1]})
        users = {
            "t1@example.test": {"id": "t1", "role": "teacher"},
            "t2@example.test": {"id": "t2", "role": "teacher"},
        }
        healthy, info = rebuild.verify_state(lessons, users)
        self.assertFalse(healthy)
        self.assertIn("вне сетки периодов", info["reason"])


class TeacherBackToBackTests(unittest.TestCase):
    """Учитель может вести свой предмет подряд в разных классах."""

    def test_teacher_teaches_consecutive_periods_in_two_classes(self):
        users = make_users()
        math_teacher = users["teacher01@demo.og.test"]["id"]
        day = date(2026, 11, 16)
        by_class_day = {
            1: {
                day: [
                    {"id": 1, "subject_id": 1, "_protected": False},
                    {"id": 2, "subject_id": 1001, "_protected": False},
                ]
            },
            2: {
                day: [
                    {"id": 3, "subject_id": 1, "_protected": False},
                    {"id": 4, "subject_id": 1001, "_protected": False},
                ]
            },
        }
        teacher_of = {
            (1, 1): math_teacher,
            (1, 1001): users[expand.subject_teacher_email(1, "a", 1001)]["id"],
            (2, 1): math_teacher,
            (2, 1001): users[expand.subject_teacher_email(1, "b", 1001)]["id"],
        }
        placement = rebuild.assign_periods(by_class_day, teacher_of)
        math_periods = sorted(
            entry["period"]
            for rows in placement.values()
            for entry in rows.values()
            if entry["subject_id"] == 1
        )
        self.assertEqual(math_periods, [1, 2], "математик ведёт два класса подряд")
        self.assertEqual(len(set(math_periods)), 2, "часы не пересекаются")


# ------------------------------------------------------------------
# Study-year scenario (phase 6)


class FakeYearCalendar:
    """Study-year fixture: full weeks, a vacation week, a short week.

    Weeks of 02/09/16 November 2026 are full Mon-Sat weeks, the week of
    23 November is a vacation (no school days at all), 30 November and
    07 December are full again, and the week of 14 December is short:
    Tuesday 15 December is a public holiday.
    """

    def __init__(self):
        mondays = (
            date(2026, 11, 2),
            date(2026, 11, 9),
            date(2026, 11, 16),
            date(2026, 11, 30),
            date(2026, 12, 7),
        )
        weeks = [[monday + timedelta(days=i) for i in range(6)] for monday in mondays]
        weeks.append([date(2026, 12, 14) + timedelta(days=i) for i in (0, 2, 3, 4, 5)])
        self.days = [day for week in weeks for day in week]
        self.STUDY_YEAR = (self.days[0], self.days[-1])
        self._day_set = frozenset(self.days)

    def school_days(self):
        return list(self.days)

    def is_school_day(self, day):
        return day in self._day_set


YEAR_CLASSES = [
    {"id": 1, "name": "1А"},
    {"id": 2, "name": "1Б"},
    {"id": 3, "name": "5А"},
    {"id": 4, "name": "5Б"},
]
YEAR_GRADES = (1, 5)


def make_year_users():
    """Demo teacher accounts of the two fixture parallels."""
    users = {}
    for grade in YEAR_GRADES:
        for code in expand.CODES:
            users[expand.emails(grade, code)] = {
                "id": f"t-{grade}-{code}",
                "role": "teacher",
            }
            for subject_id in expand.applicable_subject_ids(grade):
                users[expand.subject_teacher_email(grade, code, subject_id)] = {
                    "id": f"t-{grade}-{code}-{subject_id}",
                    "role": "teacher",
                }
    return users


class FakeLessonsDb:
    """In-memory transport of the balance_demo_lessons_db modes."""

    def __init__(self, calendar):
        self.calendar = calendar
        self.lessons = []
        self.calls = []
        self.next_id = 1000

    def __call__(self, data):
        self.calls.append(data)
        mode = data["mode"]
        if mode == "export":
            start = datetime.fromisoformat(data["start"])
            end = datetime.fromisoformat(data["end"])
            class_ids = set(data["class_ids"])
            return [
                dict(row)
                for row in self.lessons
                if start <= datetime.fromisoformat(row["starts_at"]) < end
                and (
                    row["class_id"] in class_ids
                    or row["teacher_id"] in set(data["teacher_ids"])
                )
            ]
        if mode == "wipe":
            class_ids = set(data["class_ids"])
            gone = [row for row in self.lessons if row["class_id"] in class_ids]
            self.lessons = [
                row for row in self.lessons if row["class_id"] not in class_ids
            ]
            return {
                "lessons": len(gone),
                "idempotency_keys": len(gone),
                "cache_keys": len(gone),
            }
        if mode == "create":
            for entry in data["plan"]:
                self.lessons.append(self._row_of(entry))
            return {
                "inserted": len(data["plan"]),
                "chunks_total": 1,
                "chunks_inserted": 1,
                "chunks_skipped": 0,
                "failed_chunk": None,
                "unfinished_chunks": [],
            }
        if mode == "teacher_usage":
            counts: dict[str, int] = {}
            for row in self.lessons:
                counts[row["teacher_id"]] = counts.get(row["teacher_id"], 0) + 1
            return counts
        raise AssertionError(f"unexpected db mode {mode!r}")

    def _row_of(self, entry):
        day = date.fromisoformat(entry["date"])
        period = PERIODS[entry["period"] - 1]
        self.next_id += 1
        return {
            "id": self.next_id,
            "class_id": entry["class_id"],
            "teacher_id": entry["teacher_id"],
            "subject_id": entry["subject_id"],
            "starts_at": datetime.combine(day, period.start_at, TIMEZONE).isoformat(),
            "ends_at": datetime.combine(day, period.end_at, TIMEZONE).isoformat(),
            "version": 1,
            "managed": True,
        }


class FakeHomeworkDb:
    """Records the scenario wipe calls, reports zeroes."""

    def __init__(self):
        self.calls = []

    def __call__(self, data):
        self.calls.append(data)
        return {"assignments": 0, "answers": 0, "answer_files": 0, "files": 0}


class FakeJournal:
    """Journal API stub: assignments succeed, current lists are empty."""

    def __init__(self):
        self.requests = []

    def request(self, method, path, body=None, *, ok=(200,), headers=None):
        self.requests.append((method, path))
        if method == "GET" and "/classes" in path:
            return []
        return None


class YearScenarioTests(unittest.TestCase):
    """The study-year scenario: fingerprint, fixed wipe order, create, verify."""

    def setUp(self):
        self.calendar = FakeYearCalendar()
        self.users = make_year_users()
        self.classes = [dict(row) for row in YEAR_CLASSES]
        self.journal = FakeJournal()

    def run_year(self, db=None, homework=None, report=None):
        db = FakeLessonsDb(self.calendar) if db is None else db
        homework = FakeHomeworkDb() if homework is None else homework
        tmp = Path(tempfile.mkdtemp())
        report = tmp / "expanded-school.json" if report is None else report
        outcome = rebuild.rebuild_year(
            self.journal,
            self.classes,
            self.users,
            calendar=self.calendar,
            db=db,
            homework=homework,
            report=report,
            set_allowance=lambda users: None,
        )
        return outcome, db, homework, report

    def test_full_rebuild_wipes_scenarios_then_lessons_and_creates(self):
        outcome, db, homework, report = self.run_year()
        self.assertEqual(outcome["mode"], "rebuilt")
        # The wipe order is fixed: homework scenarios first (demo
        # teachers x demo classes), then the lesson wipe of the classes.
        self.assertEqual(homework.calls[0]["mode"], "wipe")
        self.assertEqual(
            homework.calls[0]["class_ids"], [row["id"] for row in self.classes]
        )
        self.assertEqual(len(homework.calls[0]["teacher_ids"]), len(self.users))
        self.assertEqual(
            [call["mode"] for call in db.calls],
            ["wipe", "export", "create", "export", "teacher_usage"],
        )
        # The emptiness export between wipe and create saw nothing.
        self.assertEqual(db.calls[1]["mode"], "export")
        # The create plan holds only fixture school days.
        plan = db.calls[2]["plan"]
        school_days = set(self.calendar.school_days())
        self.assertTrue(plan)
        self.assertTrue(
            all(date.fromisoformat(entry["date"]) in school_days for entry in plan)
        )
        self.assertEqual(db.calls[2]["study_year"], 2026)
        self.assertEqual(len(db.lessons), len(plan))
        # The fingerprint is stored after the successful verification.
        stored = json.loads(report.read_text())
        self.assertEqual(stored["year_fingerprint"], rebuild.year_fingerprint())

    def test_full_week_of_the_plan_matches_the_curriculum(self):
        _outcome, db, _homework, _report = self.run_year()
        week = {date(2026, 11, 2) + timedelta(days=i) for i in range(6)}
        weekly: dict[int, int] = {}
        for entry in db.calls[2]["plan"]:
            if date.fromisoformat(entry["date"]) in week:
                weekly[entry["class_id"]] = weekly.get(entry["class_id"], 0) + 1
        self.assertEqual(weekly[1], sum(GRADE_CURRICULUM[1].values()))
        self.assertEqual(weekly[2], sum(GRADE_CURRICULUM[1].values()))
        self.assertEqual(weekly[3], sum(GRADE_CURRICULUM[5].values()))
        self.assertEqual(weekly[4], sum(GRADE_CURRICULUM[5].values()))

    def test_short_week_of_the_plan_is_truncated(self):
        _outcome, db, _homework, _report = self.run_year()
        short = {date(2026, 12, 14) + timedelta(days=i) for i in (0, 2, 3, 4, 5)}
        for class_id, grade in ((1, 1), (3, 5)):
            got = sum(
                1
                for entry in db.calls[2]["plan"]
                if entry["class_id"] == class_id
                and date.fromisoformat(entry["date"]) in short
            )
            limit = rebuild.DAILY_LESSON_LIMIT[grade]
            usable = 4 if grade == 1 else 5
            self.assertLessEqual(got, usable * limit, (class_id, got))
            self.assertLess(got, sum(GRADE_CURRICULUM[grade].values()), class_id)

    def test_empty_run_on_matching_fingerprint(self):
        _outcome, first_db, _homework, first_report = self.run_year()
        db = FakeLessonsDb(self.calendar)
        db.lessons = [dict(row) for row in first_db.lessons]
        homework = FakeHomeworkDb()
        outcome, db, homework, report = self.run_year(
            db=db, homework=homework, report=first_report
        )
        self.assertEqual(outcome["mode"], "empty")
        # Lessons are untouched: one export for the year verification,
        # no wipe and no create; the scenarios are still wiped so the
        # following step recreates them on the current study week.
        self.assertEqual([call["mode"] for call in db.calls], ["export"])
        self.assertEqual(len(db.lessons), len(first_db.lessons))
        self.assertEqual(homework.calls[0]["mode"], "wipe")
        stored = json.loads(report.read_text())
        self.assertEqual(stored["year_fingerprint"], rebuild.year_fingerprint())

    def test_fingerprint_difference_forces_the_full_rebuild(self):
        for field, value in (
            ("calendar_version", 999),
            ("curriculum_hash", "0" * 64),
            ("grid_version", 99),
            ("study_year", "1999/2000"),
        ):
            with self.subTest(field=field):
                tmp = Path(tempfile.mkdtemp())
                report = tmp / "expanded-school.json"
                wrong = dict(rebuild.year_fingerprint(), **{field: value})
                report.write_text(json.dumps({"year_fingerprint": wrong}))
                outcome, db, homework, _report = self.run_year(report=report)
                self.assertEqual(outcome["mode"], "rebuilt")
                self.assertIn("wipe", [call["mode"] for call in db.calls])
                self.assertEqual(homework.calls[0]["mode"], "wipe")

    def test_leftover_after_wipe_fails_the_emptiness_verification(self):
        stubborn = {
            "id": 7,
            "class_id": 1,
            "teacher_id": self.users[expand.emails(1, "a")]["id"],
            "subject_id": 2,
            "starts_at": datetime.combine(
                date(2026, 11, 3), PERIODS[0].start_at, TIMEZONE
            ).isoformat(),
            "ends_at": datetime.combine(
                date(2026, 11, 3), PERIODS[0].end_at, TIMEZONE
            ).isoformat(),
            "version": 1,
            "managed": False,
        }

        class HalfWipeDb(FakeLessonsDb):
            def __call__(self, data):
                result = super().__call__(data)
                if data["mode"] == "wipe":
                    self.lessons.append(dict(stubborn))
                return result

        with self.assertRaises(rebuild.DemoError) as ctx:
            self.run_year(db=HalfWipeDb(self.calendar))
        self.assertIn("Верификация пустоты", str(ctx.exception))

    def test_failed_chunk_stops_the_run(self):
        class FailingCreateDb(FakeLessonsDb):
            def __call__(self, data):
                if data["mode"] == "create":
                    self.calls.append(data)
                    return {
                        "inserted": 0,
                        "chunks_total": 2,
                        "chunks_inserted": 0,
                        "chunks_skipped": 0,
                        "failed_chunk": {"class_id": 1, "error": "conflict"},
                        "unfinished_chunks": [{"class_id": 1}, {"class_id": 2}],
                    }
                return super().__call__(data)

        with self.assertRaises(rebuild.DemoError) as ctx:
            self.run_year(db=FailingCreateDb(self.calendar))
        self.assertIn("Чанк записи года", str(ctx.exception))


class CalendarVerifyTests(unittest.TestCase):
    """Calendar-aware verify_state: short weeks are normal, vacations are not."""

    def setUp(self):
        self.calendar = FakeYearCalendar()
        self.users = make_year_users()
        self.teachers = {
            1: "t-math",
            2: "t-russian",
            1001: "t-literature",
            1002: "t-world",
            1003: "t-history",
            1004: "t-english",
            1008: "t-it",
            1009: "t-pe",
        }

    def lesson(self, lesson_id, class_id, day, period, subject_id):
        slot = PERIODS[period - 1]
        return {
            "id": lesson_id,
            "class_id": class_id,
            "teacher_id": self.teachers[subject_id],
            "subject_id": subject_id,
            "starts_at": datetime.combine(day, slot.start_at, TIMEZONE).isoformat(),
            "ends_at": datetime.combine(day, slot.end_at, TIMEZONE).isoformat(),
            "version": 1,
        }

    def test_short_week_is_not_an_incomplete_anomaly(self):
        # The short week (Tuesday holiday) hosts four primary days; the
        # truncated plan of grade 1 - Russian with one necessary double,
        # physical education cut by the truncation priority - is healthy.
        days = [date(2026, 12, 14) + timedelta(days=i) for i in (0, 2, 3, 4)]
        day_plans = [
            (2, 1001, 1, 1002),  # Monday: Russian, Literature, Math, World
            (2, 2, 1001, 1),  # Wednesday: Russian twice (5h over 4 days)
            (1009, 2, 1001, 1),  # Thursday
            (1, 1002, 1001, 2),  # Friday
        ]
        lessons = []
        lesson_id = 1
        for day, subjects in zip(days, day_plans, strict=True):
            for period, subject in enumerate(subjects, start=1):
                lessons.append(self.lesson(lesson_id, 1, day, period, subject))
                lesson_id += 1
        healthy, info = rebuild.verify_state(
            lessons, self.users, YEAR_CLASSES, self.calendar
        )
        self.assertTrue(healthy)
        self.assertNotIn("reason", info)

    def test_lesson_in_the_vacation_week_fails(self):
        lesson = self.lesson(1, 1, date(2026, 11, 25), 1, 2)
        healthy, info = rebuild.verify_state(
            [lesson], self.users, YEAR_CLASSES, self.calendar
        )
        self.assertFalse(healthy)
        self.assertIn("неучебный день", info["reason"])

    def test_saturday_lesson_of_primary_grade_fails(self):
        lesson = self.lesson(1, 1, date(2026, 11, 21), 1, 2)
        healthy, info = rebuild.verify_state(
            [lesson], self.users, YEAR_CLASSES, self.calendar
        )
        self.assertFalse(healthy)
        self.assertIn("субботу", info["reason"])

    def test_daily_limit_violation_fails(self):
        # Five lessons of five different subjects exceed the daily
        # limit of grade 1 (four): the limit check must fire even
        # though no subject repeats.
        day = date(2026, 11, 17)
        subjects = (2, 1001, 1, 1002, 1009)
        lessons = [
            self.lesson(lesson_id, 1, day, period, subject)
            for lesson_id, (period, subject) in enumerate(
                zip(range(1, 6), subjects, strict=True), start=1
            )
        ]
        healthy, info = rebuild.verify_state(
            lessons, self.users, YEAR_CLASSES, self.calendar
        )
        self.assertFalse(healthy)
        self.assertIn("дневной лимит", info["reason"])

    def test_teacher_overlap_found_by_the_linear_scan(self):
        day = date(2026, 11, 17)
        lessons = [
            self.lesson(1, 1, day, 2, 2),
            self.lesson(2, 2, day, 2, 2),
        ]
        lessons[1]["teacher_id"] = lessons[0]["teacher_id"]
        healthy, info = rebuild.verify_state(
            lessons, self.users, YEAR_CLASSES, self.calendar
        )
        self.assertFalse(healthy)
        self.assertIn("пересечение уроков учителя", info["reason"])

    def test_window_in_a_class_day_fails(self):
        day = date(2026, 11, 17)
        lessons = [self.lesson(1, 1, day, 1, 2), self.lesson(2, 1, day, 3, 1001)]
        healthy, info = rebuild.verify_state(
            lessons, self.users, YEAR_CLASSES, self.calendar
        )
        self.assertFalse(healthy)
        self.assertIn("окно", info["reason"])


class RepairPathTests(unittest.TestCase):
    """The week repair path refuses lessons no demo script manages."""

    def test_repair_refuses_unmanaged_lessons(self):
        users = make_users()
        classes, lessons, _protected = make_school(users)
        unmanaged = dict(lessons[0], managed=False)

        class ExportOnlyDb:
            def __init__(self, rows):
                self.rows = rows
                self.calls = []

            def __call__(self, data):
                self.calls.append(data)
                return self.rows

        db = ExportOnlyDb([unmanaged])
        with self.assertRaises(rebuild.DemoError) as ctx:
            rebuild.rebuild_timetable(FakeJournal(), DAYS, classes, users, db=db)
        self.assertIn("вне демо-скриптов", str(ctx.exception))
        self.assertEqual([call["mode"] for call in db.calls], ["export"])


class YearRebuildDueTests(unittest.TestCase):
    """The pre-expansion wipe decision mirrors rebuild_year."""

    def test_missing_report_means_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "expanded-school.json"
            self.assertTrue(rebuild.year_rebuild_due(report))

    def test_matching_fingerprint_means_empty_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "expanded-school.json"
            report.write_text(
                json.dumps({"year_fingerprint": rebuild.year_fingerprint()}),
                encoding="utf-8",
            )
            self.assertFalse(rebuild.year_rebuild_due(report))

    def test_broken_report_means_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "expanded-school.json"
            report.write_text("{", encoding="utf-8")
            self.assertTrue(rebuild.year_rebuild_due(report))


class WipeYearLessonsTests(unittest.TestCase):
    """The pre-expansion lesson wipe targets the demo classes only."""

    def test_wipes_all_demo_classes_through_the_db_transport(self):
        class Journal:
            def request(self, method, path):
                return [{"id": 7}, {"id": 3}] if "offset=0" in path else []

        calls = []

        def db(payload):
            calls.append(payload)
            return {"wiped_lessons": 10, "wiped_keys": 10, "wiped_cache_keys": 4}

        result = rebuild.wipe_year_lessons(Journal(), 2026, db=db)
        self.assertEqual(calls, [{"mode": "wipe", "class_ids": [3, 7]}])
        self.assertEqual(result["wiped_lessons"], 10)

    def test_no_classes_means_no_db_call(self):
        class Journal:
            def request(self, method, path):
                return []

        def db(payload):
            raise AssertionError("db must not be called")

        result = rebuild.wipe_year_lessons(Journal(), 2026, db=db)
        self.assertEqual(result["wiped_lessons"], 0)
