"""Ключевые проверки детерминированного переноса вне-сеточных уроков."""

import importlib.util
import sys
import unittest
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from typing import ClassVar

_TOOLS_DIR = str(Path(__file__).resolve().parent)
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_TOOLS_DIR, _SCHEDULE_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from schedule_service.domain.school_periods import (
    EFFECTIVE_FROM,
    TIMEZONE,
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


remap = load_module("remap_offgrid_lessons.py")

HORIZON_FIRST = EFFECTIVE_FROM
HORIZON_LAST = EFFECTIVE_FROM + timedelta(days=14)


def local_dt(day: date, hh: int, mm: int, ss: int = 0) -> datetime:
    """Местное школьное время как осознанная дата."""
    return datetime.combine(day, time(hh, mm, ss), TIMEZONE)


def lesson(
    lesson_id: int,
    day: date,
    start: time,
    end: time,
    *,
    class_id: int = 1,
    teacher_id: str = "00000000-0000-0000-0000-000000000001",
    subject_id: int = 1,
    status: str = "planned",
):
    """Собирает урок с границами в местном времени школы."""
    return remap.LessonRecord(
        id=lesson_id,
        class_id=class_id,
        teacher_id=teacher_id,
        subject_id=subject_id,
        starts_at=local_dt(day, start.hour, start.minute, start.second),
        ends_at=local_dt(day, end.hour, end.minute, end.second),
        status=status,
        version=1,
    )


def on_grid(
    lesson_id: int,
    day: date,
    period_number: int,
    *,
    class_id: int = 1,
    teacher_id: str = "00000000-0000-0000-0000-000000000001",
):
    """Собирает урок точно в границах периода сетки."""
    period = next(p for p in remap.PERIODS if p.number == period_number)
    return lesson(
        lesson_id,
        day,
        period.start_at,
        period.end_at,
        class_id=class_id,
        teacher_id=teacher_id,
    )


DAY = EFFECTIVE_FROM + timedelta(days=1)


class NearestPeriodTest(unittest.TestCase):
    """Кандидат — ближайший по началу период; при равенстве — ранний."""

    def test_near_first_period_maps_to_it(self):
        decision = remap.plan_remaps([lesson(1, DAY, time(9, 3), time(9, 48))])[0]
        self.assertEqual(decision.period.number, 1)
        self.assertEqual(decision.new_starts_at, local_dt(DAY, 9, 0).astimezone(UTC))
        self.assertEqual(decision.new_ends_at, local_dt(DAY, 9, 45).astimezone(UTC))

    def test_tie_chooses_earlier_period(self):
        # 09:27:30 одинаково далеко от 09:00 и 09:55 — берётся ранний.
        lesson_tied = lesson(1, DAY, time(9, 27, 30), time(10, 12, 30))
        self.assertEqual(remap.nearest_period(time(9, 27, 30)).number, 1)
        decision = remap.plan_remaps([lesson_tied])[0]
        self.assertEqual(decision.period.number, 1)

    def test_nearest_uses_start_only_not_midpoint(self):
        # 11:52 ближе к 11:55 (3 минуты), чем к 11:00 — кандидат 4.
        decision = remap.plan_remaps([lesson(1, DAY, time(11, 52), time(12, 10))])[0]
        self.assertEqual(decision.period.number, 4)


class OccupiedPeriodTest(unittest.TestCase):
    """Занятый период обходится следующим свободным, не предыдущим."""

    def test_class_conflict_moves_to_next_free_period(self):
        busy = on_grid(10, DAY, 2)
        moved = remap.plan_remaps([busy, lesson(11, DAY, time(10, 2), time(10, 47))])
        decision = next(d for d in moved if d.lesson.id == 11)
        self.assertEqual(decision.period.number, 3)

    def test_teacher_conflict_moves_to_next_free_period(self):
        other_class_busy = on_grid(
            10, DAY, 2, class_id=9, teacher_id="00000000-0000-0000-0000-000000000002"
        )
        target = lesson(
            11,
            DAY,
            time(10, 2),
            time(10, 47),
            teacher_id="00000000-0000-0000-0000-000000000002",
        )
        decision = remap.plan_remaps([other_class_busy, target])[0]
        self.assertEqual(decision.period.number, 3)

    def test_cancelled_occupant_does_not_block(self):
        canceled = on_grid(10, DAY, 2)
        canceled_offgrid = lesson(11, DAY, time(9, 3), time(9, 48), status="canceled")
        decision = remap.plan_remaps([canceled, canceled_offgrid])[0]
        self.assertEqual(decision.period.number, 1)

    def test_fully_busy_day_is_not_placed(self):
        data = [on_grid(number, DAY, number) for number in range(1, 8)]
        data.append(lesson(8, DAY, time(9, 3), time(9, 48)))
        decision = next(d for d in remap.plan_remaps(data) if d.lesson.id == 8)
        self.assertFalse(decision.placed)
        self.assertIsNone(decision.period)
        self.assertIsNone(decision.new_starts_at)
        self.assertIsNone(decision.new_ends_at)


class CancelledLessonTest(unittest.TestCase):
    """Отменённый урок переносится без проверок и не занимает периоды."""

    def test_canceled_moves_to_occupied_period(self):
        busy = on_grid(10, DAY, 2)
        canceled = lesson(11, DAY, time(10, 2), time(10, 47), status="canceled")
        decision = next(
            d for d in remap.plan_remaps([busy, canceled]) if d.lesson.id == 11
        )
        self.assertTrue(decision.placed)
        self.assertEqual(decision.period.number, 2)

    def test_canceled_placement_does_not_block_planned(self):
        canceled = lesson(10, DAY, time(10, 2), time(10, 47), status="canceled")
        planned = lesson(11, DAY, time(10, 3), time(10, 48))
        decisions = remap.plan_remaps([canceled, planned])
        numbers = {d.lesson.id: d.period.number for d in decisions}
        self.assertEqual(numbers, {10: 2, 11: 2})


class DeterminismTest(unittest.TestCase):
    """Правило не зависит от порядка входных данных и повторного запуска."""

    def test_input_order_does_not_change_plan(self):
        data = [
            on_grid(1, DAY, 1),
            lesson(2, DAY, time(9, 4), time(9, 49)),
            lesson(3, DAY, time(9, 6), time(9, 51)),
            lesson(
                4,
                DAY,
                time(11, 8),
                time(11, 53),
                teacher_id="00000000-0000-0000-0000-000000000002",
            ),
        ]
        straight = remap.plan_remaps(data)
        reversed_input = remap.plan_remaps(list(reversed(data)))

        def plan_key(decisions):
            return tuple(
                (d.lesson.id, d.period.number if d.period else None) for d in decisions
            )

        self.assertEqual(plan_key(straight), plan_key(reversed_input))

    def test_second_pass_over_remapped_data_changes_nothing(self):
        data = [
            on_grid(1, DAY, 1),
            lesson(2, DAY, time(9, 4), time(9, 49)),
            lesson(3, DAY, time(9, 6), time(9, 51)),
            lesson(4, DAY, time(10, 8), time(10, 53)),
            lesson(5, DAY, time(13, 4), time(13, 49), status="canceled"),
        ]
        decisions = remap.plan_remaps(data)
        applied = list(data)
        for decision in decisions:
            assert decision.period is not None
            index = next(
                i for i, item in enumerate(applied) if item.id == decision.lesson.id
            )
            applied[index] = remap.LessonRecord(
                id=decision.lesson.id,
                class_id=decision.lesson.class_id,
                teacher_id=decision.lesson.teacher_id,
                subject_id=decision.lesson.subject_id,
                starts_at=decision.new_starts_at,
                ends_at=decision.new_ends_at,
                status=decision.lesson.status,
                version=decision.lesson.version + 1,
            )
        self.assertEqual(remap.plan_remaps(applied), [])
        self.assertEqual(remap.offgrid_lessons(applied), [])


class HorizonTest(unittest.TestCase):
    """Горизонт фиксирован: effective_from..+14 календарных дней, Пн–Сб."""

    def test_horizon_bounds_and_no_sundays(self):
        days = remap.horizon_school_days()
        self.assertEqual(days[0], HORIZON_FIRST)
        self.assertEqual(days[-1], HORIZON_LAST)
        self.assertEqual(len(days), 13)
        self.assertNotIn(6, [day.weekday() for day in days])

    def test_horizon_is_school_week_monday_to_saturday(self):
        days = remap.horizon_school_days()
        self.assertEqual(days[0].weekday(), 0)
        self.assertEqual(HORIZON_LAST - HORIZON_FIRST, timedelta(days=14))


class CheckLogicTest(unittest.TestCase):
    """Пост-проверка --check: только вне-сеточные уроки новой эпохи."""

    CLASS_NAMES: ClassVar[dict] = {1: "1А"}

    def test_check_ignores_on_grid_and_legacy_lessons(self):
        legacy_day = EFFECTIVE_FROM - timedelta(days=1)
        data = [
            on_grid(1, DAY, 3),
            lesson(2, legacy_day, time(9, 0), time(10, 0)),
        ]
        offgrid = remap.offgrid_lessons(data)
        self.assertEqual(offgrid, [])
        with redirect_stdout(StringIO()):
            self.assertEqual(remap.run_check(data, self.CLASS_NAMES), 0)

    def test_check_reports_offgrid_lessons_from_effective_from(self):
        legacy_day = EFFECTIVE_FROM - timedelta(days=1)
        data = [
            on_grid(1, DAY, 3),
            lesson(2, legacy_day, time(9, 0), time(10, 0)),
            lesson(3, DAY, time(9, 3), time(9, 48)),
            lesson(
                4,
                EFFECTIVE_FROM,
                time(15, 5),
                time(15, 50),
                class_id=7,
                status="canceled",
            ),
        ]
        offgrid = remap.offgrid_lessons(data)
        self.assertEqual([item.id for item in offgrid], [4, 3])
        with redirect_stdout(StringIO()):
            self.assertEqual(remap.run_check(data, self.CLASS_NAMES), 1)

    def test_check_after_applying_plan_is_zero(self):
        data = [
            on_grid(1, DAY, 1),
            lesson(2, DAY, time(9, 4), time(9, 49)),
        ]
        decision = remap.plan_remaps(data)[0]
        assert decision.period is not None
        assert decision.new_starts_at is not None
        assert decision.new_ends_at is not None
        remapped = [
            data[0],
            remap.LessonRecord(
                id=2,
                class_id=data[1].class_id,
                teacher_id=data[1].teacher_id,
                subject_id=data[1].subject_id,
                starts_at=decision.new_starts_at,
                ends_at=decision.new_ends_at,
                status=data[1].status,
                version=data[1].version + 1,
            ),
        ]
        self.assertEqual(remap.offgrid_lessons(remapped), [])
        with redirect_stdout(StringIO()):
            self.assertEqual(remap.run_check(remapped, self.CLASS_NAMES), 0)


class ParsingTest(unittest.TestCase):
    """Строки административного ответа разбираются без потерь зоны."""

    def test_parse_lesson_accepts_z_suffix_utc(self):
        record = remap.parse_lesson(
            {
                "id": 5,
                "class_id": 2,
                "teacher_id": "4fbd1ea2-216c-4589-ae2c-afdae6966e7c",
                "subject_id": 3,
                "starts_at": "2026-12-01T04:03:00Z",
                "ends_at": "2026-12-01T04:48:00Z",
                "status": "planned",
                "version": 4,
            }
        )
        self.assertEqual(record.id, 5)
        self.assertEqual(record.starts_at, datetime(2026, 12, 1, 4, 3, tzinfo=UTC))
        self.assertEqual(remap.school_date(record), DAY)
        self.assertTrue(remap.needs_remap(record))


if __name__ == "__main__":
    unittest.main()
