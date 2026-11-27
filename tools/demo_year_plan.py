"""Year plan generator for the demo school (spec section 3).

Pure functions without database or network access: the inputs are the
curriculum tables (tools/demo_curriculum.py), a study-year calendar (the
schedule_service.domain.school_calendar module or any object exposing
school_days()) and teacher pools keyed by (grade, subject); the output is
the plan of the whole study year as a list of
(class_id, subject, teacher, date, period) tuples.

Pipeline per parallel (all classes of one grade together):

1. spread_week_hours - greedy layout of the weekly hours over the school
   days of the grade;
2. match_teachers_and_periods - one teacher per (class, subject) pair of
   the parallel plus contiguous period blocks per class day; the block
   placement core (place_day_blocks, match_block,
   separate_adjacent_duplicates) is shared with
   rebuild_demo_timetable.assign_periods and was extracted from it;
3. day rotation - study week w (0-based from the start of the study
   year) moves template day d to weekday rotate_day(d, w mod n, n);
   periods and teachers never change;
4. truncation of short weeks - lessons are removed from the end of
   TRUNCATION_PRIORITY until the week total fits into the actual school
   days of the week x DAILY_LESSON_LIMIT; lessons mapped to weekdays
   without a school date are dropped afterwards, and a truncated day is
   re-packed inside the span of its template period block.

The module is deterministic: identical inputs always produce identical
plans, and nothing here reads the current date.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta

from demo_curriculum import (
    DAILY_LESSON_LIMIT,
    GRADE_CURRICULUM,
    SCHOOL_DAYS_PER_WEEK,
    TRUNCATION_PRIORITY,
)

PERIOD_COUNT = 7

# Default class lines of a parallel; build_year_plan accepts an explicit
# classes_by_grade mapping, so the letters only matter when it is omitted.
CLASS_LETTERS = ("a", "b", "c", "d", "e")


# ------------------------------------------------- shared matching core
#
# match_block, separate_adjacent_duplicates and place_day_blocks were
# extracted verbatim from rebuild_demo_timetable (the step-3 matching of
# the week rebuild: "class-teacher-period" assignment inside contiguous
# period blocks). rebuild_demo_timetable.assign_periods delegates to
# place_day_blocks, so the week rebuild and the year generator share one
# implementation.


def match_block(
    rows: list[dict],
    class_id,
    teacher_of: Mapping,
    busy: dict,
    periods: list[int],
) -> dict[int, int] | None:
    """Matches each lesson of a class day to a period of one block.

    A "lesson -> period" bipartite matching: the teacher of a lesson
    must be free. Periods continuing the teacher's occupied streak are
    preferred, so the working day of the teacher stays compact.
    """
    match_period_of: dict[int, int] = {}
    period_of_lesson: dict[int, int] = {}

    def candidates(index: int) -> list[int]:
        subject = rows[index]["subject_id"]
        teacher = teacher_of.get((class_id, subject))
        if not teacher:
            return []
        free = [p for p in periods if p not in busy[teacher]]
        streak = busy[teacher]
        return sorted(
            free, key=lambda p: (0 if p - 1 in streak or p + 1 in streak else 1, p)
        )

    def try_augment(index: int, seen: set[int]) -> bool:
        for period in candidates(index):
            if period in seen:
                continue
            seen.add(period)
            held = period_of_lesson.get(period)
            if held is None or try_augment(held, seen):
                match_period_of[index] = period
                period_of_lesson[period] = index
                return True
        return False

    for index in range(len(rows)):
        if not try_augment(index, set()):
            return None
    return match_period_of


def separate_adjacent_duplicates(
    rows: list[dict],
    class_id,
    period_of: dict[int, int],
    teacher_of: Mapping,
    busy: dict,
) -> None:
    """Separates same-subject lessons by swapping inside the class day.

    A swap is allowed only when both teachers are free in their new
    periods; the number of passes is bounded to avoid looping.
    """

    def teacher_of_row(index: int):
        return teacher_of.get((class_id, rows[index]["subject_id"]))

    for _round in range(10):
        swapped = False
        for i in range(len(rows)):
            for j in range(len(rows)):
                if i == j or rows[i]["subject_id"] != rows[j]["subject_id"]:
                    continue
                if abs(period_of[i] - period_of[j]) <= 1:
                    for k in range(len(rows)):
                        if (
                            k in (i, j)
                            or rows[k]["subject_id"] == rows[i]["subject_id"]
                        ):
                            continue
                        pi, _pj, pk = period_of[i], period_of[j], period_of[k]
                        ti, tk = teacher_of_row(i), teacher_of_row(k)
                        if not ti or not tk or ti == tk:
                            continue
                        between = any(
                            min(pi, pk) < period_of[m] < max(pi, pk)
                            and rows[m]["subject_id"] == rows[i]["subject_id"]
                            for m in range(len(rows))
                            if m not in (i, j, k)
                        )
                        if between:
                            continue
                        if pk not in busy[ti] and pi not in busy[tk]:
                            period_of[i], period_of[k] = pk, pi
                            busy[ti].discard(pi)
                            busy[ti].add(pk)
                            busy[tk].discard(pk)
                            busy[tk].add(pi)
                            swapped = True
                            break
                    if swapped:
                        break
            if swapped:
                break
        if not swapped:
            return


def place_day_blocks(
    rows_by_class: Mapping,
    teacher_of: Mapping,
    busy: dict,
    period_count: int,
) -> dict:
    """Places the lessons of every class of one day into period blocks.

    One class day occupies a contiguous interval of the period grid; the
    block start is searched exhaustively, the lessons inside the block
    are matched to periods with the teacher availability in mind
    (match_block) and same-subject lessons are moved apart
    (separate_adjacent_duplicates). Longer days are placed first: a
    short class day has more freedom to fit its block around the busy
    teachers.

    Args:
        rows_by_class: class key -> ordered lesson rows with a
            "subject_id" key; the order is preserved.
        teacher_of: (class key, subject) -> teacher key.
        busy: mutable teacher key -> set of taken periods of this day;
            updated in place.
        period_count: number of periods in the grid (7).

    Returns:
        class key -> {row index -> period}.

    Raises:
        ValueError: if no contiguous block fits the teacher
            availability for some class.
    """
    counts = {class_id: len(rows) for class_id, rows in rows_by_class.items()}
    max_len = max(counts.values(), default=0)
    total_periods = min(max_len + 2, period_count)
    placed = {}
    for class_id in sorted(rows_by_class, key=lambda item: (-counts[item], item)):
        rows = rows_by_class[class_id]
        count = counts[class_id]
        block = None
        for start in range(1, total_periods - count + 2):
            periods = list(range(start, start + count))
            matched = match_block(rows, class_id, teacher_of, busy, periods)
            if matched is not None:
                block = matched
                break
        if block is None:
            raise ValueError(
                f"no contiguous period block fits class {class_id!r}: "
                "teachers are busy in every block variant"
            )
        period_of = dict(block)
        separate_adjacent_duplicates(rows, class_id, period_of, teacher_of, busy)
        for index, row in enumerate(rows):
            period = period_of[index]
            teacher = teacher_of.get((class_id, row["subject_id"]))
            if teacher:
                busy[teacher].add(period)
        placed[class_id] = period_of
    return placed


# ------------------------------------------------------- day layout


def spread_week_hours(
    grade: int,
    curriculum: Mapping[int, Mapping[str, int]] | None = None,
    *,
    daily_lesson_limit: Mapping[int, int] | None = None,
    school_days_per_week: Mapping[int, int] | None = None,
    truncation_priority: tuple[str, ...] | None = None,
) -> dict[int, list[str]]:
    """Lays out the weekly hours of one grade over its school days.

    Greedy algorithm of the spec: subjects in the order of descending
    hours (ties: earlier in truncation_priority); every hour goes to
    the least loaded day where the subject appears fewer than two times
    and the daily lesson limit is not reached; on equal loads the
    smaller day number wins.

    Args:
        grade: the parallel to lay out.
        curriculum: grade -> subject -> weekly hours; defaults to the
            demo_curriculum table.
        daily_lesson_limit: grade -> maximum lessons per day.
        school_days_per_week: grade -> number of school days (5 or 6).
        truncation_priority: subjects in preservation order.

    Returns:
        day number (1..n) -> subjects in placement order.

    Raises:
        ValueError: if an hour cannot be placed without breaking the
            day limits or a subject is missing from truncation_priority.
    """
    hours = (GRADE_CURRICULUM if curriculum is None else curriculum)[grade]
    limits = DAILY_LESSON_LIMIT if daily_lesson_limit is None else daily_lesson_limit
    week_days = (
        SCHOOL_DAYS_PER_WEEK if school_days_per_week is None else school_days_per_week
    )
    priority = (
        TRUNCATION_PRIORITY if truncation_priority is None else truncation_priority
    )
    position = {subject: index for index, subject in enumerate(priority)}
    try:
        order = sorted(hours, key=lambda subject: (-hours[subject], position[subject]))
    except KeyError as error:
        raise ValueError(
            f"grade {grade}: subject {error} is missing from truncation_priority"
        ) from error
    days_count = week_days[grade]
    limit = limits[grade]
    days: dict[int, list[str]] = {day: [] for day in range(1, days_count + 1)}
    for subject in order:
        for _ in range(hours[subject]):
            candidates = [
                day
                for day in days
                if days[day].count(subject) < 2 and len(days[day]) < limit
            ]
            if not candidates:
                raise ValueError(
                    f"grade {grade}: no school day accepts another hour "
                    f"of {subject!r} within the daily limit {limit}"
                )
            day = min(candidates, key=lambda item: (len(days[item]), item))
            days[day].append(subject)
    return days


def match_teachers_and_periods(
    classes,
    day_layout: Mapping,
    teacher_pools: Mapping,
    *,
    period_count: int = PERIOD_COUNT,
) -> list:
    """Assigns teachers and periods for the template week of a parallel.

    Contract (the reusable "class-teacher-period" matching of
    rebuild_demo_timetable.plan_rebuild): every (class, subject) pair of
    the parallel is bound to one teacher of the subject pool - pairs
    with more weekly hours first, the least loaded teacher wins, the
    pool order breaks ties; this is a trimmed partition_teachers (the
    pinned protected lessons, the teacher01 guarantee and the email
    pool spreading of the week rebuild have no counterpart for the year
    generator) - and every class day takes one contiguous period block
    placed by the shared place_day_blocks matching.

    Args:
        classes: class ids of one parallel.
        day_layout: class id -> day number -> subjects (the output of
            spread_week_hours).
        teacher_pools: subject -> teacher ids of the parallel pool.
        period_count: periods in the grid (7).

    Returns:
        (class, subject, teacher, day, period) tuples of the week.

    Raises:
        ValueError: if a pool is empty or no period block fits.
    """
    ordered = sorted(classes)
    subjects = sorted(
        {
            subject
            for class_id in ordered
            for rows in day_layout[class_id].values()
            for subject in rows
        }
    )
    teacher_of: dict = {}
    for subject in subjects:
        pool = list(teacher_pools.get(subject, ()))
        if not pool:
            raise ValueError(f"teacher pool for subject {subject!r} is empty")
        hours_of = {
            class_id: sum(rows.count(subject) for rows in day_layout[class_id].values())
            for class_id in ordered
        }
        pairs = sorted(
            (class_id for class_id in ordered if hours_of[class_id]),
            key=lambda class_id: (-hours_of[class_id], class_id),
        )
        loads = [0] * len(pool)
        for class_id in pairs:
            index = min(range(len(pool)), key=lambda item: (loads[item], item))
            loads[index] += hours_of[class_id]
            teacher_of[(class_id, subject)] = pool[index]
    result = []
    all_days = sorted({day for class_id in ordered for day in day_layout[class_id]})
    for day in all_days:
        rows_by_class = {
            class_id: [{"subject_id": subject} for subject in day_layout[class_id][day]]
            for class_id in ordered
            if day_layout[class_id].get(day)
        }
        busy: dict = defaultdict(set)
        placed = place_day_blocks(rows_by_class, teacher_of, busy, period_count)
        for class_id in sorted(placed):
            rows = rows_by_class[class_id]
            for index in sorted(placed[class_id]):
                subject = rows[index]["subject_id"]
                result.append(
                    (
                        class_id,
                        subject,
                        teacher_of[(class_id, subject)],
                        day,
                        placed[class_id][index],
                    )
                )
    return result


def _verify_template_week(
    week: list,
    *,
    daily_limit: int,
    period_count: int,
) -> None:
    """Checks the hard invariants of a template week.

    Raises:
        ValueError: on a teacher double booking, a lesson outside the
            period grid, more than two lessons of one subject in a
            class day, a broken period block or a broken daily limit.
    """
    taken: set = set()
    per_class_day: dict = defaultdict(list)
    for class_id, subject, teacher, day, period in week:
        slot = (teacher, day, period)
        if slot in taken:
            raise ValueError(f"teacher {teacher!r} is double-booked at {slot}")
        taken.add(slot)
        if not 1 <= period <= period_count:
            raise ValueError(f"period {period} leaves the {period_count}-period grid")
        per_class_day[(class_id, day)].append((subject, period))
    for (class_id, day), rows in sorted(per_class_day.items()):
        if len(rows) > daily_limit:
            raise ValueError(
                f"class {class_id} day {day}: {len(rows)} lessons exceed "
                f"the daily limit {daily_limit}"
            )
        subjects = [subject for subject, _period in rows]
        for subject in sorted(set(subjects)):
            if subjects.count(subject) > 2:
                raise ValueError(
                    f"class {class_id} day {day}: subject {subject!r} "
                    "appears more than twice"
                )
        periods = sorted(period for _subject, period in rows)
        if periods != list(range(periods[0], periods[0] + len(periods))):
            raise ValueError(
                f"class {class_id} day {day}: periods {periods} "
                "do not form one contiguous block"
            )


def build_template_week(
    grade: int,
    classes,
    curriculum: Mapping[int, Mapping[str, int]],
    teacher_pools: Mapping,
    *,
    daily_lesson_limit: Mapping[int, int] | None = None,
    school_days_per_week: Mapping[int, int] | None = None,
    truncation_priority: tuple[str, ...] | None = None,
    period_count: int = PERIOD_COUNT,
) -> list:
    """Builds and verifies the template week of one parallel.

    All classes of the grade are scheduled together: the greedy day
    layout of the grade plus the shared teacher and period matching.
    The result is verified before it is returned: no teacher teaches
    two lessons at the same time, a class meets one subject at most
    twice a day, class days occupy contiguous periods and the daily
    lesson limit holds.

    Args:
        grade: the parallel.
        classes: class ids of the parallel.
        curriculum: grade -> subject -> weekly hours.
        teacher_pools: subject -> teacher ids of the parallel pool.
        daily_lesson_limit: grade -> maximum lessons per day; defaults
            to the demo_curriculum table.
        school_days_per_week: grade -> school days per week (5 or 6).
        truncation_priority: subjects in preservation order.
        period_count: periods in the grid (7).

    Returns:
        (class, subject, teacher, day, period) tuples of the template
        week.

    Raises:
        ValueError: on any invariant violation or an infeasible input.
    """
    limits = DAILY_LESSON_LIMIT if daily_lesson_limit is None else daily_lesson_limit
    layout = spread_week_hours(
        grade,
        curriculum,
        daily_lesson_limit=daily_lesson_limit,
        school_days_per_week=school_days_per_week,
        truncation_priority=truncation_priority,
    )
    week = match_teachers_and_periods(
        classes,
        {class_id: layout for class_id in classes},
        teacher_pools,
        period_count=period_count,
    )
    _verify_template_week(week, daily_limit=limits[grade], period_count=period_count)
    return week


# --------------------------------------------- rotation and short weeks


def rotate_day(day: int, shift: int, days_count: int) -> int:
    """Returns the day number after a rotation by shift positions.

    Day numbers run from 1 to days_count; rotate_day(d, 1, 6) turns
    day 6 into day 1. Negative shifts rotate backwards (used to find
    the template day behind a given weekday).
    """
    return ((day - 1 + shift) % days_count) + 1


def study_weeks(school_days: list[date]) -> list[list[date]]:
    """Groups school days into study weeks (Monday-based, in order).

    A week with at least one school day counts as a study week;
    vacation weeks are absent from the result, so the index of a week
    is its 0-based study week number from the start of the study year.
    """
    weeks: dict[date, list[date]] = {}
    for day in school_days:
        weeks.setdefault(day - timedelta(days=day.weekday()), []).append(day)
    return [weeks[monday] for monday in sorted(weeks)]


def truncate_week(
    day_plans: Mapping,
    capacity: int,
    truncation_priority: tuple[str, ...],
) -> dict:
    """Truncates a class week plan down to the weekly capacity.

    Lessons are removed from the end of truncation_priority: the
    lowest-priority subject still present loses one lesson - its last
    occurrence in the most loaded day of the class (ties: the larger
    day number) - until the week total fits into capacity.

    Args:
        day_plans: day number -> subjects in period order; not mutated.
        capacity: maximum number of lessons kept in the week.
        truncation_priority: subjects in preservation order.

    Returns:
        A new dict of day number -> new subject lists.

    Raises:
        ValueError: if the plan is over capacity but has no lessons.
    """
    result = {day: list(subjects) for day, subjects in day_plans.items()}
    total = sum(len(subjects) for subjects in result.values())
    while total > capacity:
        victim = None
        for subject in reversed(truncation_priority):
            if any(subject in subjects for subjects in result.values()):
                victim = subject
                break
        if victim is None:
            raise ValueError(
                f"week holds {total} lessons but has no subject left to truncate"
            )
        candidates = [day for day in result if victim in result[day]]
        day = max(candidates, key=lambda item: (len(result[item]), item))
        row = result[day]
        for index in range(len(row) - 1, -1, -1):
            if row[index] == victim:
                del row[index]
                break
        total -= 1
    return result


# -------------------------------------------------------- the full year


def build_year_plan(
    curriculum: Mapping[int, Mapping[str, int]],
    calendar,
    teacher_pools: Mapping,
    *,
    classes_by_grade: Mapping[int, list] | None = None,
    daily_lesson_limit: Mapping[int, int] | None = None,
    school_days_per_week: Mapping[int, int] | None = None,
    truncation_priority: tuple[str, ...] | None = None,
    period_count: int = PERIOD_COUNT,
) -> list:
    """Builds the lesson plan of the whole study year, all parallels.

    Every parallel contributes one verified template week; study week w
    places template day d on weekday rotate_day(d, w mod n, n) with
    n school days of the grade, and short weeks are truncated to their
    actual capacity (see truncate_week). Lessons that the rotation maps
    to a weekday without a school date are dropped; a truncated day is
    re-packed inside the span of its template period block, so class
    days stay contiguous.

    Args:
        curriculum: grade -> subject -> weekly hours
            (tools/demo_curriculum.GRADE_CURRICULUM).
        calendar: study-year calendar exposing school_days() -> list of
            dates (schedule_service.domain.school_calendar).
        teacher_pools: (grade as str, subject) -> teacher ids; pools of
            different parallels must not share teachers.
        classes_by_grade: grade -> class ids; defaults to
            f"{grade}{letter}" for CLASS_LETTERS.
        daily_lesson_limit: overrides the demo_curriculum table.
        school_days_per_week: overrides the demo_curriculum table.
        truncation_priority: overrides the demo_curriculum table.
        period_count: periods in the grid (7).

    Returns:
        (class_id, subject, teacher, date, period) tuples over all
        school days of the year; deterministic for identical inputs.

    Raises:
        ValueError: on a missing teacher pool or any invariant
            violation inside a template week.
    """
    limits = DAILY_LESSON_LIMIT if daily_lesson_limit is None else daily_lesson_limit
    week_lengths = (
        SCHOOL_DAYS_PER_WEEK if school_days_per_week is None else school_days_per_week
    )
    priority = (
        TRUNCATION_PRIORITY if truncation_priority is None else truncation_priority
    )
    if classes_by_grade is None:
        classes_by_grade = {
            grade: [f"{grade}{letter}" for letter in CLASS_LETTERS]
            for grade in curriculum
        }
    weeks = study_weeks(calendar.school_days())
    plan: list = []
    for grade in sorted(curriculum):
        days_count = week_lengths[grade]
        daily_limit = limits[grade]
        classes = classes_by_grade[grade]
        pools: dict = {}
        for subject in curriculum[grade]:
            key = (str(grade), subject)
            pool = teacher_pools.get(key)
            if not pool:
                raise ValueError(f"teacher pool for {key!r} is missing or empty")
            pools[subject] = pool
        template = build_template_week(
            grade,
            classes,
            curriculum,
            pools,
            daily_lesson_limit=daily_lesson_limit,
            school_days_per_week=school_days_per_week,
            truncation_priority=truncation_priority,
            period_count=period_count,
        )
        template_days: dict = {class_id: {} for class_id in classes}
        teacher_of_subject: dict = {class_id: {} for class_id in classes}
        for class_id, subject, teacher, day, period in template:
            template_days[class_id].setdefault(day, []).append(
                (subject, teacher, period)
            )
            teacher_of_subject[class_id][subject] = teacher
        for by_day in template_days.values():
            for day in by_day:
                by_day[day].sort(key=lambda row: row[2])
        for week_number, week_dates in enumerate(weeks):
            shift = week_number % days_count
            usable = {
                day.weekday() + 1: day
                for day in week_dates
                if day.weekday() < days_count
            }
            if not usable:
                continue
            capacity = len(usable) * daily_limit
            for class_id in classes:
                by_day = template_days[class_id]
                full = {
                    day: [subject for subject, _teacher, _period in rows]
                    for day, rows in by_day.items()
                }
                total = sum(len(subjects) for subjects in full.values())
                kept = (
                    truncate_week(full, capacity, priority)
                    if total > capacity
                    else full
                )
                for weekday in sorted(usable):
                    source_day = rotate_day(weekday, -shift, days_count)
                    rows = by_day.get(source_day, [])
                    subjects = kept.get(source_day, [])
                    if not subjects:
                        continue
                    teachers = teacher_of_subject[class_id]
                    if len(subjects) == len(rows):
                        for subject, _teacher, period in rows:
                            plan.append(
                                (
                                    class_id,
                                    subject,
                                    teachers[subject],
                                    usable[weekday],
                                    period,
                                )
                            )
                    else:
                        first_period = rows[0][2]
                        for offset, subject in enumerate(subjects):
                            plan.append(
                                (
                                    class_id,
                                    subject,
                                    teachers[subject],
                                    usable[weekday],
                                    first_period + offset,
                                )
                            )
    return plan
