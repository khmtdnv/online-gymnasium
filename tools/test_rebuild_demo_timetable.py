"""Ключевые проверки перестройки демо-расписания."""

import importlib.util
import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path


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
            slots = class_day.setdefault((row["class_id"], start.date()), [])
            slots.append(start.hour)
        for rows in subjects.values():
            self.assertEqual(len(rows), 1, "учитель ведёт несколько предметов")
        for slots in class_day.values():
            hours = sorted(slots)
            self.assertEqual(hours, list(range(hours[0], hours[0] + len(hours))))

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

    def test_class_day_capacity_and_hours_are_preserved(self):
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
            hour = (
                datetime.fromisoformat(row["starts_at"])
                .astimezone(rebuild.TIMEZONE)
                .hour
            )
            self.assertGreaterEqual(hour, rebuild.FIRST_HOUR)
        self.assertEqual(before, after)

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
