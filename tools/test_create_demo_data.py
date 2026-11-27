"""Ключевые проверки безопасного наполнения демонстрационной школы."""

import importlib.util
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)


def load_demo_module():
    path = Path(__file__).with_name("create_demo_data.py")
    spec = importlib.util.spec_from_file_location("create_demo_data", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        self.demo = load_demo_module()

    def test_accounts_are_unique(self):
        accounts = self.demo.build_accounts()
        self.assertEqual(len(accounts), 79)
        self.assertEqual(len({a["email"] for a in accounts}), 79)
        self.assertEqual(sum(a["role"] == "student" for a in accounts), 56)
        self.assertTrue(all(a["first_name"] and a["last_name"] for a in accounts))

    def test_scenario_span_follows_the_school_calendar(self):
        # 2026-10-21 sits in a full quarter week: the span collects the
        # weekdays of the current and the following study week.
        days = self.demo.scenario_span(today=date(2026, 10, 21))
        self.assertGreaterEqual(len(days), 9)
        self.assertEqual(days[0], date(2026, 10, 19))
        self.assertEqual(days[-1], date(2026, 10, 30))
        self.assertTrue(all(day.weekday() < 5 for day in days))
        calendar = self.demo.school_calendar
        self.assertTrue(all(calendar.is_school_day(day) for day in days))

    def test_scenario_span_skips_the_vacation_week(self):
        # 2026-11-04 is inside the autumn vacation (31.10 - 08.11):
        # the span starts at the nearest following study week.
        days = self.demo.scenario_span(today=date(2026, 11, 4))
        self.assertEqual(days[0], date(2026, 11, 9))
        self.assertGreaterEqual(len(days), 9)
        self.assertTrue(all(day.weekday() < 5 for day in days))

    def test_lesson_slot_does_not_overlap_existing_lesson(self):
        day = date(2026, 10, 21)
        existing = [
            {
                # 08:30–09:30 местного времени: перекрывает период 1
                # (09:00–09:45), но не период 2 (09:55–10:40).
                "starts_at": "2026-10-21T03:30:00Z",
                "ends_at": "2026-10-21T04:30:00Z",
                "status": "planned",
            }
        ]
        start = self.demo.choose_lesson_start(day, existing)
        self.assertEqual(
            start,
            datetime(2026, 10, 21, 9, 55, tzinfo=ZoneInfo("Asia/Yekaterinburg")),
        )
        # Выбранное время — точное начало одного из периодов сетки.
        self.assertIn(start.time(), [p.start_at for p in self.demo.PERIODS])

    def test_lesson_start_raises_when_no_period_is_free(self):
        day = date(2026, 10, 21)
        existing = [
            {
                "starts_at": datetime.combine(
                    day, period.start_at, self.demo.TIMEZONE
                ).isoformat(),
                "ends_at": datetime.combine(
                    day, period.end_at, self.demo.TIMEZONE
                ).isoformat(),
                "status": "planned",
            }
            for period in self.demo.PERIODS
        ]
        with self.assertRaises(self.demo.DemoError):
            self.demo.choose_lesson_start(day, existing)

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


class CurrentStudyWeekTests(unittest.TestCase):
    """Selection of the current study week from the school calendar."""

    def setUp(self):
        self.demo = load_demo_module()

    def test_week_of_a_school_day_is_returned_as_is(self):
        # 2026-11-18 (Wednesday) belongs to the study week of 16-21
        # November; Saturday 21.11 is a school day of the 6-day week.
        week = self.demo.current_study_week(date(2026, 11, 18))
        self.assertEqual(week[0], date(2026, 11, 16))
        self.assertEqual(week[-1], date(2026, 11, 21))
        calendar = self.demo.school_calendar
        self.assertTrue(all(calendar.is_school_day(day) for day in week))

    def test_date_in_vacation_selects_the_nearest_following_study_week(self):
        # 2026-11-04 is inside the autumn vacation: the week of its
        # Monday holds no school day, so the next study week wins.
        week = self.demo.current_study_week(date(2026, 11, 4))
        self.assertEqual(week[0], date(2026, 11, 9))
        self.assertEqual(week[-1], date(2026, 11, 14))

    def test_week_of_the_last_quarter_day_stays_that_week(self):
        # Quarter 1 ends on Friday 30.10; Saturday 31.10 is already the
        # autumn vacation, so the study week ends on the 30th.
        week = self.demo.current_study_week(date(2026, 10, 30))
        self.assertEqual(week[0], date(2026, 10, 26))
        self.assertEqual(week[-1], date(2026, 10, 30))

    def test_sunday_after_a_study_week_moves_to_the_next_one(self):
        # 2026-11-22 is the Sunday after the study week of Nov 16-21:
        # every school day of that week is already in the past, so the
        # scenarios move to the following study week.
        week = self.demo.current_study_week(date(2026, 11, 22))
        self.assertEqual(week[0], date(2026, 11, 23))
        self.assertEqual(week[-1], date(2026, 11, 28))

    def test_saturday_evening_keeps_the_current_week(self):
        # Saturday 2026-11-21 is still a school day of its own week.
        week = self.demo.current_study_week(date(2026, 11, 21))
        self.assertEqual(week[0], date(2026, 11, 16))
        self.assertEqual(week[-1], date(2026, 11, 21))

    def test_date_past_the_year_end_returns_the_last_study_week(self):
        week = self.demo.current_study_week(date(2027, 6, 1))
        self.assertEqual(week[-1], date(2027, 5, 29))


class ScenarioLessonTests(unittest.TestCase):
    """The scenario lessons come from the current study week."""

    def setUp(self):
        self.demo = load_demo_module()

    def lesson(self, lesson_id, day, period, subject_id, teacher_id):
        slot = self.demo.PERIODS[period - 1]
        return {
            "id": lesson_id,
            "class_id": 1,
            "teacher_id": teacher_id,
            "subject_id": subject_id,
            "starts_at": datetime.combine(
                day, slot.start_at, self.demo.TIMEZONE
            ).isoformat(),
            "ends_at": datetime.combine(
                day, slot.end_at, self.demo.TIMEZONE
            ).isoformat(),
            "status": "planned",
        }

    def week_rows(self):
        """Planned lessons of class 1A over the study week of 16-21 Nov."""
        subjects = (2, 1001, 1, 1002, 1009)
        rows = []
        lesson_id = 100
        for day_offset in range(6):
            day = date(2026, 11, 16) + timedelta(days=day_offset)
            for period in range(1, 5):
                subject = subjects[(day_offset + period) % len(subjects)]
                rows.append(self.lesson(lesson_id, day, period, subject, "t-a"))
                lesson_id += 1
        return rows

    def test_scenarios_use_the_lessons_of_the_current_study_week(self):
        rows = self.week_rows()
        now = datetime(2026, 11, 17, 12, 0, tzinfo=self.demo.TIMEZONE)
        issued, deadline = self.demo.choose_scenario_lessons(rows, [], now)
        week_days = {date(2026, 11, 16) + timedelta(days=i) for i in range(6)}
        self.assertEqual(len(issued), 7)
        self.assertEqual(len({row["id"] for row in issued}), 7)
        for row in issued:
            day = (
                datetime.fromisoformat(row["starts_at"])
                .astimezone(self.demo.TIMEZONE)
                .date()
            )
            self.assertIn(day, week_days)
        if deadline is not None:
            self.assertEqual(deadline["subject_id"], issued[0]["subject_id"])
            self.assertGreater(
                datetime.fromisoformat(deadline["starts_at"]),
                datetime.fromisoformat(issued[0]["starts_at"]),
            )
            self.assertGreater(datetime.fromisoformat(deadline["starts_at"]), now)

    def test_deadline_search_extends_into_the_following_week(self):
        rows = self.week_rows()
        now = datetime(2026, 11, 21, 12, 0, tzinfo=self.demo.TIMEZONE)
        # issued[0] is a Literature lesson (subject 1001); the only
        # later future lesson of the subject lives in the next week.
        extra = [
            self.lesson(900, date(2026, 11, 24), 1, 1001, "t-a"),
        ]
        _issued, deadline = self.demo.choose_scenario_lessons(rows, extra, now)
        self.assertIsNotNone(deadline)
        self.assertEqual(deadline["id"], 900)

    def test_fewer_than_seven_lessons_are_rejected(self):
        rows = self.week_rows()[:6]
        with self.assertRaises(self.demo.DemoError):
            self.demo.choose_scenario_lessons(
                rows, [], datetime(2026, 11, 17, 12, 0, tzinfo=self.demo.TIMEZONE)
            )


if __name__ == "__main__":
    unittest.main()


class ApiRetryTests(unittest.TestCase):
    """The API client respects the login rate limit (HTTP 429)."""

    def setUp(self):
        self.demo = load_demo_module()

    def test_retry_after_429_returns_the_following_response(self):
        import io
        import time as time_module
        from unittest import mock

        class FakeResponse:
            def __init__(self, status, payload, headers):
                self.code = status
                self._stream = io.BytesIO(payload)
                self.headers = headers

            def read(self):
                return self._stream.read()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        responses = [
            FakeResponse(429, b"", {"Retry-After": "0", "Set-Cookie": ""}),
            FakeResponse(
                200,
                b'{"ok": true}',
                {"Content-Type": "application/json", "Set-Cookie": ""},
            ),
        ]

        class FakeOpener:
            def open(self, request, timeout):
                return responses.pop(0)

        api = self.demo.Api("http://demo")
        api.opener = FakeOpener()
        with mock.patch.object(time_module, "sleep") as sleep:
            self.assertEqual(api.request("GET", "/x"), {"ok": True})
            sleep.assert_called_once_with(0.0)

    def test_exhausted_429_raises_demo_error(self):
        import time as time_module
        from unittest import mock

        class FakeResponse:
            def __init__(self):
                self.code = 429
                self.headers = {"Retry-After": "", "Set-Cookie": ""}

            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class FakeOpener:
            def open(self, request, timeout):
                return FakeResponse()

        api = self.demo.Api("http://demo")
        api.opener = FakeOpener()
        with (
            mock.patch.object(time_module, "sleep"),
            self.assertRaises(self.demo.DemoError) as ctx,
        ):
            api.request("GET", "/x")
        self.assertIn("HTTP 429", str(ctx.exception))
