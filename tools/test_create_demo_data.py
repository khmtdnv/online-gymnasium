"""Ключевые проверки безопасного наполнения демонстрационной школы."""

import importlib.util
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).with_name("create_demo_data.py")
        self.assertTrue(path.exists(), "Нет скрипта создания демо-данных")
        spec = importlib.util.spec_from_file_location("create_demo_data", path)
        self.demo = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.demo
        spec.loader.exec_module(self.demo)

    def test_accounts_and_dates_have_no_duplicates_or_weekends(self):
        accounts = self.demo.build_accounts()
        self.assertEqual(len(accounts), 79)
        self.assertEqual(len({a["email"] for a in accounts}), 79)
        self.assertEqual(sum(a["role"] == "student" for a in accounts), 56)
        self.assertTrue(all(a["first_name"] and a["last_name"] for a in accounts))
        days = self.demo.school_days(date(2026, 10, 21))
        self.assertEqual(len(days), 10)
        self.assertEqual(days[0], date(2026, 10, 19))
        self.assertEqual(days[-1], date(2026, 10, 30))
        self.assertTrue(all(day.weekday() < 5 for day in days))

    def test_lesson_slot_does_not_overlap_existing_lesson(self):
        day = date(2026, 10, 21)
        existing = [
            {
                "starts_at": "2026-10-21T03:30:00Z",
                "ends_at": "2026-10-21T04:30:00Z",
                "status": "planned",
            }
        ]
        start = self.demo.choose_lesson_start(day, existing)
        self.assertEqual(
            start, datetime(2026, 10, 21, 10, tzinfo=ZoneInfo("Asia/Yekaterinburg"))
        )

    def test_existing_user_is_not_recreated_or_password_reset(self):
        class NoWrites:
            def request(self, *args, **kwargs):
                raise AssertionError("Нельзя менять существующего пользователя")

        account = self.demo.build_accounts()[0]
        existing = {account["email"]: {**account, "id": "known-id", "is_active": True}}
        result = self.demo.ensure_user(NoWrites(), account, existing)
        self.assertEqual(result["id"], "known-id")
        existing[account["email"]]["role"] = "admin"
        with self.assertRaises(self.demo.DemoError):
            self.demo.ensure_user(NoWrites(), account, existing)


if __name__ == "__main__":
    unittest.main()
