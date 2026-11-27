"""Unit tests for the demo year plan generator (tools/demo_year_plan.py)."""

import sys
import unittest
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parent)
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_TOOLS_DIR, _SCHEDULE_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from demo_curriculum import (
    DAILY_LESSON_LIMIT,
    GRADE_CURRICULUM,
    SCHOOL_DAYS_PER_WEEK,
    TRUNCATION_PRIORITY,
)
from demo_year_plan import (
    build_template_week,
    build_year_plan,
    spread_week_hours,
    study_weeks,
    truncate_week,
)
from schedule_service.domain import school_calendar

GRADES = range(1, 12)
LETTERS = ("a", "b", "c", "d", "e")
CLASSES_PER_PARALLEL = 5
# One subject teacher per class line, exactly as tools/expand_demo_school.py
# creates accounts: every (grade, subject) pool holds POOL_SIZE teachers.
POOL_SIZE = 5
STUDY_WEEKS = 35
FULL_YEAR_LESSONS = 53375
# Actual plan volume fixed after the first calculation: the full year
# holds FULL_YEAR_LESSONS lessons, the short-week truncation removes
# TRUNCATED_LESSONS of them (priority removals down to the capacity of
# actual school days x DAILY_LESSON_LIMIT plus the whole day
# compositions dropped on holidays and quarter boundaries).
YEAR_LESSONS = 51565
TRUNCATED_LESSONS = FULL_YEAR_LESSONS - YEAR_LESSONS


def make_classes():
    """Synthetic parallel classes: '1a'..'1e', ..., '11a'..'11e'."""
    return {grade: [f"{grade}{letter}" for letter in LETTERS] for grade in GRADES}


def make_pools():
    """Teacher pools keyed by (grade, subject), the expand_demo_school scheme."""
    pools = {}
    for grade in GRADES:
        for subject in GRADE_CURRICULUM[grade]:
            pools[(str(grade), subject)] = [
                f"t{grade:02d}-{letter}-{subject}" for letter in LETTERS
            ]
    return pools


def grade_of(class_id):
    """Returns the grade of a synthetic class id like '10c'."""
    return int(class_id[:-1])


class SpreadWeekHoursTests(unittest.TestCase):
    """Greedy layout of weekly hours over the school days of a grade."""

    def test_layout_is_feasible_and_deterministic_for_every_grade(self):
        for grade in GRADES:
            first = spread_week_hours(grade, GRADE_CURRICULUM)
            second = spread_week_hours(grade, GRADE_CURRICULUM)
            self.assertEqual(first, second, grade)
            days_count = SCHOOL_DAYS_PER_WEEK[grade]
            limit = DAILY_LESSON_LIMIT[grade]
            self.assertEqual(sorted(first), list(range(1, days_count + 1)))
            placed = Counter()
            for day, subjects in first.items():
                self.assertLessEqual(len(subjects), limit, (grade, day))
                counts = Counter(subjects)
                self.assertLessEqual(max(counts.values()), 2, (grade, day))
                placed.update(subjects)
            self.assertEqual(placed, Counter(GRADE_CURRICULUM[grade]), grade)

    def test_layout_orders_subjects_by_hours_then_priority(self):
        # The first laid-out subject has the most hours; ties follow
        # TRUNCATION_PRIORITY, so the first hour always lands on day 1.
        layout = spread_week_hours(7, GRADE_CURRICULUM)
        top_hours = max(GRADE_CURRICULUM[7].values())
        leading = [
            subject
            for subject, hours in GRADE_CURRICULUM[7].items()
            if hours == top_hours
        ]
        leading.sort(key=TRUNCATION_PRIORITY.index)
        self.assertEqual(layout[1][0], leading[0])

    def test_infeasible_layout_is_rejected(self):
        # Six hours of one subject cannot fit a five-day week with one
        # lesson per day and a daily limit of one.
        with self.assertRaises(ValueError):
            spread_week_hours(
                1,
                {1: {"Физическая культура": 6}},
                daily_lesson_limit={1: 1},
                school_days_per_week={1: 5},
            )


class TemplateWeekTests(unittest.TestCase):
    """Template week of a parallel with the shared matching inside."""

    @classmethod
    def setUpClass(cls):
        cls.classes = make_classes()
        cls.pools = make_pools()

    def pools_of(self, grade):
        return {
            subject: self.pools[(str(grade), subject)]
            for subject in GRADE_CURRICULUM[grade]
        }

    def test_template_week_is_verified_for_every_parallel(self):
        # build_template_week verifies its result itself; reaching the
        # size check means no invariant was violated.
        for grade in GRADES:
            week = build_template_week(
                grade,
                self.classes[grade],
                GRADE_CURRICULUM,
                self.pools_of(grade),
            )
            self.assertEqual(
                len(week),
                CLASSES_PER_PARALLEL * sum(GRADE_CURRICULUM[grade].values()),
                grade,
            )
            teachers = {}
            for class_id, subject, teacher, day, period in week:
                self.assertIn(period, range(1, 8))
                self.assertIn(day, range(1, SCHOOL_DAYS_PER_WEEK[grade] + 1))
                teachers[(class_id, subject)] = teacher
            # one subject of a class is taught by exactly one teacher
            self.assertEqual(
                len(teachers),
                CLASSES_PER_PARALLEL * len(GRADE_CURRICULUM[grade]),
            )

    def test_template_week_uses_only_pool_teachers(self):
        week = build_template_week(
            9, self.classes[9], GRADE_CURRICULUM, self.pools_of(9)
        )
        allowed = {teacher for pool in self.pools_of(9).values() for teacher in pool}
        for _class_id, _subject, teacher, _day, _period in week:
            self.assertIn(teacher, allowed)

    def test_pools_of_different_parallels_do_not_intersect(self):
        seen = set()
        for key, pool in sorted(self.pools.items()):
            overlap = seen.intersection(pool)
            self.assertFalse(overlap, (key, overlap))
            seen.update(pool)

    def test_missing_pool_is_rejected(self):
        with self.assertRaises(ValueError):
            build_template_week(
                5,
                self.classes[5],
                GRADE_CURRICULUM,
                {subject: [] for subject in GRADE_CURRICULUM[5]},
            )


class YearPlanTests(unittest.TestCase):
    """Full-year plan over all 11 synthetic parallels."""

    @classmethod
    def setUpClass(cls):
        cls.classes = make_classes()
        cls.pools = make_pools()
        cls.plan = build_year_plan(
            GRADE_CURRICULUM,
            school_calendar,
            cls.pools,
            classes_by_grade=cls.classes,
        )
        cls.weeks = study_weeks(school_calendar.school_days())
        cls.by_class = defaultdict(list)
        for class_id, subject, teacher, day, period in cls.plan:
            cls.by_class[class_id].append((subject, teacher, day, period))

    def lessons_of_class_week(self, class_id, week_index):
        """Returns (subject, day, period) of one class in one study week."""
        days = set(self.weeks[week_index])
        return [
            (subject, day, period)
            for subject, _teacher, day, period in self.by_class[class_id]
            if day in days
        ]

    def day_subjects(self, class_id, week_index, weekday):
        """Returns the sorted subjects of one class weekday."""
        return sorted(
            subject
            for subject, day, _period in self.lessons_of_class_week(
                class_id, week_index
            )
            if day.weekday() + 1 == weekday
        )

    def test_year_volume(self):
        weekly_total = sum(sum(row.values()) for row in GRADE_CURRICULUM.values())
        self.assertEqual(weekly_total, 305)
        self.assertEqual(len(self.weeks), STUDY_WEEKS)
        self.assertEqual(weekly_total * CLASSES_PER_PARALLEL * STUDY_WEEKS, 53375)
        self.assertEqual(len(self.plan), YEAR_LESSONS)
        self.assertEqual(FULL_YEAR_LESSONS - len(self.plan), TRUNCATED_LESSONS)

    def test_lessons_only_on_school_days_inside_the_grade_week(self):
        for class_id, _subject, _teacher, day, _period in self.plan:
            self.assertTrue(school_calendar.is_school_day(day), day)
            # grades 1-4 run a five-day week: Saturdays stay empty
            self.assertLess(day.weekday(), SCHOOL_DAYS_PER_WEEK[grade_of(class_id)])

    def test_periods_stay_inside_the_seven_period_grid(self):
        for _class_id, _subject, _teacher, _day, period in self.plan:
            self.assertIn(period, range(1, 8))

    def test_no_teacher_conflicts_in_any_week_of_the_year(self):
        taken = set()
        for _class_id, _subject, teacher, day, period in self.plan:
            slot = (teacher, day, period)
            self.assertNotIn(slot, taken, slot)
            taken.add(slot)

    def test_at_most_two_lessons_of_a_subject_per_class_day(self):
        counts = Counter()
        for class_id, subject, _teacher, day, _period in self.plan:
            counts[(class_id, day, subject)] += 1
        self.assertLessEqual(max(counts.values()), 2)

    def test_class_days_are_contiguous_and_within_daily_limits(self):
        periods_by_class_day = defaultdict(list)
        for class_id, _subject, _teacher, day, period in self.plan:
            periods_by_class_day[(class_id, day)].append(period)
        for (class_id, day), periods in periods_by_class_day.items():
            grade = grade_of(class_id)
            ordered = sorted(periods)
            self.assertEqual(
                ordered,
                list(range(ordered[0], ordered[0] + len(ordered))),
                (class_id, day),
            )
            self.assertLessEqual(
                len(ordered), DAILY_LESSON_LIMIT[grade], (class_id, day)
            )

    def test_every_week_fits_actual_school_days_times_limit(self):
        for grade in GRADES:
            days_count = SCHOOL_DAYS_PER_WEEK[grade]
            limit = DAILY_LESSON_LIMIT[grade]
            for week_index, week in enumerate(self.weeks):
                usable = sum(1 for day in week if day.weekday() < days_count)
                if not usable:
                    continue
                for class_id in self.classes[grade]:
                    got = len(self.lessons_of_class_week(class_id, week_index))
                    self.assertLessEqual(got, usable * limit, (class_id, week_index))

    def test_short_week_of_23_february_follows_truncation_priority(self):
        week_index = next(
            index
            for index, week in enumerate(self.weeks)
            if any(day == date(2027, 2, 22) for day in week)
        )
        holiday = date(2027, 2, 23)
        for grade in GRADES:
            days_count = SCHOOL_DAYS_PER_WEEK[grade]
            limit = DAILY_LESSON_LIMIT[grade]
            layout = spread_week_hours(grade, GRADE_CURRICULUM)
            shift = week_index % days_count
            week = self.weeks[week_index]
            usable = {day.weekday() + 1 for day in week if day.weekday() < days_count}
            capacity = len(usable) * limit
            full_total = sum(GRADE_CURRICULUM[grade].values())
            for class_id in self.classes[grade]:
                lessons = self.lessons_of_class_week(class_id, week_index)
                # nothing on the public holiday and the week fits
                self.assertFalse(
                    any(day == holiday for _s, day, _p in lessons), class_id
                )
                self.assertLessEqual(len(lessons), capacity, class_id)
                # expected composition: the full week truncated by the
                # priority rule, then the holiday weekday dropped
                full = {day: list(subjects) for day, subjects in layout.items()}
                kept = truncate_week(full, capacity, TRUNCATION_PRIORITY)
                dropped_day = ((2 - 1 - shift) % days_count) + 1  # Tuesday
                expected = Counter()
                removed = Counter()
                for day, subjects in full.items():
                    removed.update(subjects)
                for day, subjects in kept.items():
                    removed.subtract(subjects)
                    if day != dropped_day:
                        expected.update(subjects)
                actual = Counter(subject for subject, _d, _p in lessons)
                self.assertEqual(actual, expected, class_id)
                if full_total > capacity:
                    # priority removal fired and started from the tail
                    self.assertEqual(
                        sum(removed.values()), full_total - capacity, class_id
                    )
                    lowest = next(
                        subject
                        for subject in reversed(TRUNCATION_PRIORITY)
                        if removed[subject]
                    )
                    self.assertEqual(lowest, "Физическая культура", class_id)

    def test_short_week_of_23_february_keeps_priority_lessons_in_grade_1(self):
        # Grade 1 holds 20 weekly hours; the week of 23 February keeps
        # four school days (Tue, Thu-Sat) and four lessons per day: the
        # truncation removes the seven lowest-priority lessons, physical
        # education drops from three to zero, the core subjects survive.
        lessons = self.lessons_of_class_week("1a", 22)
        self.assertEqual(len(lessons), 13)
        pe = sum(1 for subject, _d, _p in lessons if subject == "Физическая культура")
        self.assertEqual(pe, 0)
        self.assertGreaterEqual(
            sum(1 for subject, _d, _p in lessons if subject == "Русский язык"), 3
        )

    def test_rotation_of_week_one(self):
        grade = 5
        days_count = SCHOOL_DAYS_PER_WEEK[grade]
        template = build_template_week(
            grade,
            self.classes[grade],
            GRADE_CURRICULUM,
            {
                subject: self.pools[(str(grade), subject)]
                for subject in GRADE_CURRICULUM[grade]
            },
        )
        template_days = defaultdict(dict)
        for class_id, subject, _teacher, day, period in template:
            template_days[class_id].setdefault(day, []).append((period, subject))
        week_index = 1  # the second study week: full Monday-to-Saturday
        shift = week_index % days_count
        for class_id in self.classes[grade]:
            lessons = self.lessons_of_class_week(class_id, week_index)
            by_date = defaultdict(list)
            for subject, day, period in lessons:
                by_date[day].append((period, subject))
            self.assertEqual(len(lessons), sum(GRADE_CURRICULUM[grade].values()))
            for day, rows in by_date.items():
                source_day = ((day.weekday() + 1 - 1 - shift) % days_count) + 1
                expected = [
                    subject
                    for _period, subject in sorted(template_days[class_id][source_day])
                ]
                self.assertEqual(
                    [subject for _period, subject in sorted(rows)],
                    expected,
                    (class_id, day),
                )
            # the full week keeps the subject multiset of the template
            self.assertEqual(
                Counter(subject for subject, _d, _p in lessons),
                Counter(GRADE_CURRICULUM[grade]),
            )

    def test_rotation_changes_day_compositions_between_weeks(self):
        # Week 0 places template day 2 on Tuesday (k = 0), week 1 places
        # template day 1 there (k = 1): the weekday composition changes
        # while the week keeps its subjects.
        self.assertNotEqual(
            self.day_subjects("5a", 0, 2), self.day_subjects("5a", 1, 2)
        )
        self.assertEqual(
            len(self.lessons_of_class_week("5a", 0)),
            sum(GRADE_CURRICULUM[5].values())
            - len(spread_week_hours(5, GRADE_CURRICULUM)[1]),
        )

    def test_plan_is_deterministic(self):
        second = build_year_plan(
            GRADE_CURRICULUM,
            school_calendar,
            self.pools,
            classes_by_grade=self.classes,
        )
        self.assertEqual(self.plan, second)

    def test_missing_pool_is_rejected(self):
        pools = dict(self.pools)
        del pools[("7", "Физика")]
        with self.assertRaises(ValueError):
            build_year_plan(
                GRADE_CURRICULUM,
                school_calendar,
                pools,
                classes_by_grade=self.classes,
            )


if __name__ == "__main__":
    unittest.main()
