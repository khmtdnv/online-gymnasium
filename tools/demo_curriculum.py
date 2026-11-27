"""Curriculum data for the demo school: weekly hours, limits, priorities.

Pure data, no scheduling logic. The hours source is a typical weekly
curriculum plan of a Russian general education school (FGOS/BUP); the
hygienic limits of the study load (daily lesson caps, week length for
grades 1-4 vs 5-11) follow SanPiN 1.2.3685-21. Subject names are taken
verbatim from the school catalog (SUBJECTS in tools/expand_demo_school.py);
grades 1-4 study five days a week, grades 5-11 six days.

Weekly hour targets: the full weekly norm of a living school (SanPiN
1.2.3685-21 ceilings: grade 1 <= 21, grades 2-4 <= 23, grade 5 <= 29,
grade 6 <= 30, grades 7-8 <= 32, grade 9 <= 34, grades 10-11 <= 33/34).
Senior grades (10-11) carry profile hours: the mandatory core plus an
extended profile load (deeper Mathematics and English) - profile hours
are assigned to existing subjects only, the subject catalog is fixed.
"""

from __future__ import annotations

SUBJECT_GRADES: dict[str, tuple[int, int]] = {
    "Математика": (1, 11),
    "Русский язык": (1, 11),
    "Литература": (1, 11),
    "Физическая культура": (1, 11),
    "Английский язык": (2, 11),
    "Окружающий мир": (1, 5),
    "История": (5, 11),
    "Информатика": (4, 11),
    "Биология": (6, 11),
    "География": (6, 11),
    "Физика": (7, 11),
}

# N  | Рус | Литер | Матем | Англ | Окр | Ист | Биол | Геогр | Физ | Информ | Физра | Σ
# 1  |  6  |   4   |   5   |  —   |  2  |  —  |  —   |  —    |  —  |   —    |   3   | 20
# 2  |  6  |   4   |   5   |  3   |  3  |  —  |  —   |  —    |  —  |   —    |   3   | 24→Σ below
# ...
GRADE_CURRICULUM: dict[int, dict[str, int]] = {
    # Grade 1: 4 lessons/day week (SanPiN daily cap 4, 5-day) => 20 h.
    1: {
        "Русский язык": 6,
        "Литература": 4,
        "Математика": 5,
        "Окружающий мир": 2,
        "Физическая культура": 3,
    },
    # Grade 2: 5 lessons/day, 5-day, SanPiN ceiling 23.
    2: {
        "Русский язык": 5,
        "Литература": 4,
        "Математика": 5,
        "Английский язык": 3,
        "Окружающий мир": 3,
        "Физическая культура": 3,
    },
    # Grade 3: SanPiN ceiling 23.
    3: {
        "Русский язык": 5,
        "Литература": 3,
        "Математика": 5,
        "Английский язык": 3,
        "Окружающий мир": 3,
        "Физическая культура": 4,
    },
    # Grade 4: SanPiN ceiling 23.
    4: {
        "Русский язык": 5,
        "Литература": 3,
        "Математика": 5,
        "Английский язык": 3,
        "Окружающий мир": 3,
        "Информатика": 2,
        "Физическая культура": 2,
    },
    # Grade 5: 6-day, cap 6/day, SanPiN ceiling 29.
    5: {
        "Русский язык": 6,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 3,
        "Окружающий мир": 2,
        "История": 2,
        "Информатика": 2,
        "Физическая культура": 3,
    },
    # Grade 6: SanPiN ceiling 30.
    6: {
        "Русский язык": 6,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 3,
        "История": 2,
        "Биология": 2,
        "География": 2,
        "Информатика": 2,
        "Физическая культура": 4,
    },
    # Grade 7: cap 7/day, SanPiN ceiling 32.
    7: {
        "Русский язык": 4,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 3,
        "История": 3,
        "Биология": 2,
        "География": 2,
        "Физика": 2,
        "Информатика": 2,
        "Физическая культура": 4,
    },
    # Grade 8: SanPiN ceiling 32.
    8: {
        "Русский язык": 4,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 3,
        "История": 3,
        "Биология": 2,
        "География": 2,
        "Физика": 2,
        "Информатика": 2,
        "Физическая культура": 4,
    },
    # Grade 9: SanPiN ceiling 34.
    9: {
        "Русский язык": 4,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 4,
        "История": 3,
        "Биология": 2,
        "География": 2,
        "Физика": 2,
        "Информатика": 3,
        "Физическая культура": 4,
    },
    # Grade 10: profile load, SanPiN ceiling 33.
    10: {
        "Русский язык": 3,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 4,
        "История": 3,
        "Биология": 2,
        "География": 2,
        "Физика": 3,
        "Информатика": 3,
        "Физическая культура": 3,
    },
    # Grade 11: profile load, SanPiN ceiling 33/34.
    11: {
        "Русский язык": 3,
        "Литература": 3,
        "Математика": 6,
        "Английский язык": 4,
        "История": 3,
        "Биология": 2,
        "География": 2,
        "Физика": 3,
        "Информатика": 3,
        "Физическая культура": 3,
    },
}

# Maximum lessons per school day (SanPiN 1.2.3685-21):
# grade 1 - 4; grades 2-4 - 5; grades 5-6 - 6; grades 7-11 - 7.
DAILY_LESSON_LIMIT: dict[int, int] = {
    1: 4,
    2: 5,
    3: 5,
    4: 5,
    5: 6,
    6: 6,
    7: 7,
    8: 7,
    9: 7,
    10: 7,
    11: 7,
}

# School days per week: primary school (grades 1-4) - five, others - six.
SCHOOL_DAYS_PER_WEEK: dict[int, int] = {
    1: 5,
    2: 5,
    3: 5,
    4: 5,
    5: 6,
    6: 6,
    7: 6,
    8: 6,
    9: 6,
    10: 6,
    11: 6,
}

# Preservation order for truncating short weeks: lessons are removed from
# the end of this tuple first, so the head subjects survive the longest.
TRUNCATION_PRIORITY: tuple[str, ...] = (
    "Русский язык",
    "Математика",
    "Литература",
    "История",
    "Английский язык",
    "Биология",
    "География",
    "Физика",
    "Окружающий мир",
    "Информатика",
    "Физическая культура",
)


def check_feasibility(
    *,
    grade_curriculum: dict[int, dict[str, int]] | None = None,
    subject_grades: dict[str, tuple[int, int]] | None = None,
    daily_lesson_limit: dict[int, int] | None = None,
    school_days_per_week: dict[int, int] | None = None,
    truncation_priority: tuple[str, ...] | None = None,
) -> None:
    """Validate the curriculum tables; raise ValueError on any violation.

    Any argument may be omitted to check the module tables themselves;
    passing modified copies checks alternative data (used by tests).
    """
    curriculum = GRADE_CURRICULUM if grade_curriculum is None else grade_curriculum
    applicability = SUBJECT_GRADES if subject_grades is None else subject_grades
    lesson_limits = (
        DAILY_LESSON_LIMIT if daily_lesson_limit is None else daily_lesson_limit
    )
    week_days = (
        SCHOOL_DAYS_PER_WEEK if school_days_per_week is None else school_days_per_week
    )
    priority = (
        TRUNCATION_PRIORITY if truncation_priority is None else truncation_priority
    )

    if len(set(priority)) != len(priority) or set(priority) != set(applicability):
        raise ValueError(
            "TRUNCATION_PRIORITY must be a permutation of SUBJECT_GRADES keys"
        )
    if not set(curriculum) == set(lesson_limits) == set(week_days):
        raise ValueError(
            "GRADE_CURRICULUM, DAILY_LESSON_LIMIT and SCHOOL_DAYS_PER_WEEK "
            "must cover the same grades"
        )
    for grade, row in curriculum.items():
        limit = lesson_limits[grade]
        days = week_days[grade]
        total = sum(row.values())
        if total > days * limit:
            raise ValueError(
                f"Grade {grade}: {total} weekly hours exceed the capacity "
                f"of {days} school days x {limit} lessons"
            )
        for subject, hours in row.items():
            if hours < 1:
                raise ValueError(
                    f"Grade {grade}: subject {subject!r} has non-positive hours"
                )
            if hours > 2 * days:
                raise ValueError(
                    f"Grade {grade}: subject {subject!r} has {hours} hours, "
                    f"more than two per school day ({days} days)"
                )
            span = applicability.get(subject)
            if span is None:
                raise ValueError(f"Grade {grade}: unknown subject {subject!r}")
            low, high = span
            if not low <= grade <= high:
                raise ValueError(
                    f"Grade {grade}: subject {subject!r} is applicable in "
                    f"grades {low}-{high} and must not have hours here"
                )


check_feasibility()
