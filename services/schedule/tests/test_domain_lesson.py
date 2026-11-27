from datetime import UTC, datetime
from uuid import UUID

import pytest

from schedule_service.domain.lesson import (
    InvalidLessonInterval,
    InvalidSchoolPeriod,
    Lesson,
    LessonAlreadyCanceled,
)
from schedule_service.domain.school_periods import PERIODS, TIMEZONE, period_for

# Локальное время школы (Asia/Yekaterinburg, UTC+5) переводится в UTC сдвигом
# на пять часов: первый период 09:00–09:45 — это 04:00–04:45Z (см. spec).
LESSON_DAY = datetime(2026, 9, 10, tzinfo=UTC)


def _utc_period(
    day: datetime, hours: tuple[int, int, int, int]
) -> tuple[datetime, datetime]:
    start_h, start_m, end_h, end_m = hours
    return (
        day.replace(hour=start_h, minute=start_m),
        day.replace(hour=end_h, minute=end_m),
    )


ALL_SEVEN_PERIODS_IN_UTC = [
    (hours, period.number)
    for hours, period in zip(
        (
            (4, 0, 4, 45),
            (4, 55, 5, 40),
            (6, 0, 6, 45),
            (6, 55, 7, 40),
            (8, 0, 8, 45),
            (8, 55, 9, 40),
            (10, 0, 10, 45),
        ),
        PERIODS,
        strict=True,
    )
]


def test_valid_data_created_valid_domain_object() -> None:
    domain_object = Lesson.create(
        class_id=1,
        teacher_id=UUID(int=1),
        subject_id=1,
        starts_at=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 4, 45, tzinfo=UTC),
    )

    assert domain_object.id is None
    assert domain_object.status == "planned"
    assert domain_object.version == 1


def test_invalid_timerange_raises_domain_error() -> None:
    with pytest.raises(InvalidLessonInterval):
        Lesson.create(
            class_id=1,
            teacher_id=UUID(int=1),
            subject_id=1,
            starts_at=datetime(2026, 9, 10, 4, 45, tzinfo=UTC),
            ends_at=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
        )


def test_equal_timerange_raises_domain_error() -> None:
    instant = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)

    with pytest.raises(InvalidLessonInterval):
        Lesson.create(
            class_id=1,
            teacher_id=UUID(int=1),
            subject_id=1,
            starts_at=instant,
            ends_at=instant,
        )


def test_create_rejects_lesson_crossing_midnight() -> None:
    with pytest.raises(InvalidLessonInterval):
        Lesson.create(
            class_id=10,
            teacher_id=UUID(int=100),
            subject_id=1000,
            starts_at=datetime(2026, 9, 10, 23, tzinfo=UTC),
            ends_at=datetime(2026, 9, 11, 1, tzinfo=UTC),
        )


def test_reschedule_rejects_lesson_crossing_midnight() -> None:
    lesson = Lesson.create(
        class_id=10,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 4, 45, tzinfo=UTC),
    )

    with pytest.raises(InvalidLessonInterval):
        lesson.reschedule(
            starts_at=datetime(2026, 9, 10, 23, tzinfo=UTC),
            ends_at=datetime(2026, 9, 11, 1, tzinfo=UTC),
        )


def test_reschedule_changes_interval_and_preserves_other_lesson_data() -> None:
    lesson = Lesson(
        id=501,
        class_id=10,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 9, 10, 4, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 4, 45, tzinfo=UTC),
        status="planned",
        version=3,
    )

    lesson.reschedule(
        starts_at=datetime(2026, 9, 10, 6, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 6, 45, tzinfo=UTC),
    )

    assert lesson.starts_at == datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
    assert lesson.ends_at == datetime(2026, 9, 10, 6, 45, tzinfo=UTC)
    assert lesson.id == 501
    assert lesson.class_id == 10
    assert lesson.teacher_id == UUID(int=100)
    assert lesson.subject_id == 1000
    assert lesson.status == "planned"
    assert lesson.version == 3


def test_cancel_changes_status_and_rejects_second_cancellation() -> None:
    lesson = Lesson(
        id=501,
        class_id=10,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 9, 10, 10, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 11, tzinfo=UTC),
        status="planned",
        version=3,
    )

    lesson.cancel()

    assert lesson.status == "canceled"
    assert lesson.id == 501
    assert lesson.version == 3

    with pytest.raises(LessonAlreadyCanceled):
        lesson.cancel()


@pytest.mark.parametrize(("hours", "number"), ALL_SEVEN_PERIODS_IN_UTC)
def test_period_for_matches_each_grid_period_exactly(hours, number) -> None:
    starts_at, ends_at = _utc_period(LESSON_DAY, hours)

    matched = period_for(starts_at, ends_at)

    assert matched is not None
    assert matched.number == number


def test_period_for_accepts_any_school_date_and_explicit_offset() -> None:
    """Валидация не зависит от даты: сетка действует и до effective_from."""
    starts_at = datetime(2026, 9, 10, 9, 0, tzinfo=TIMEZONE)
    ends_at = datetime(2026, 9, 10, 9, 45, tzinfo=TIMEZONE)

    matched = period_for(starts_at, ends_at)

    assert matched is not None
    assert matched.number == 1


@pytest.mark.parametrize(
    ("hours", "comment"),
    [
        ((4, 1, 4, 46), "сдвиг начала на минуту (09:01)"),
        ((4, 0, 4, 50), "неверная длительность (09:00–09:50)"),
        ((5, 45, 6, 30), "время в перемену (10:45–11:30)"),
        ((10, 10, 10, 55), "после седьмого урока (15:10–15:55)"),
        ((4, 0, 5, 40), "начало первого, конец второго"),
    ],
)
def test_period_for_returns_none_for_off_grid_times(hours, comment) -> None:
    starts_at, ends_at = _utc_period(LESSON_DAY, hours)

    assert period_for(starts_at, ends_at) is None, comment


def test_period_for_returns_none_when_local_dates_differ() -> None:
    starts_at = datetime(2026, 11, 30, 19, 0, tzinfo=UTC)
    ends_at = datetime(2026, 12, 1, 19, 45, tzinfo=UTC)

    assert period_for(starts_at, ends_at) is None


@pytest.mark.parametrize(("hours", "number"), ALL_SEVEN_PERIODS_IN_UTC)
def test_create_accepts_each_school_period(hours, number) -> None:
    starts_at, ends_at = _utc_period(LESSON_DAY, hours)

    lesson = Lesson.create(
        class_id=1,
        teacher_id=UUID(int=1),
        subject_id=1,
        starts_at=starts_at,
        ends_at=ends_at,
    )

    assert lesson.starts_at == starts_at
    assert lesson.ends_at == ends_at


@pytest.mark.parametrize(
    "hours",
    [(4, 1, 4, 46), (4, 0, 4, 50), (5, 45, 6, 30), (10, 10, 10, 55)],
)
def test_create_rejects_off_grid_school_times(hours) -> None:
    starts_at, ends_at = _utc_period(LESSON_DAY, hours)

    with pytest.raises(InvalidSchoolPeriod):
        Lesson.create(
            class_id=1,
            teacher_id=UUID(int=1),
            subject_id=1,
            starts_at=starts_at,
            ends_at=ends_at,
        )


def test_create_rejects_period_times_in_different_days() -> None:
    with pytest.raises(InvalidLessonInterval):
        Lesson.create(
            class_id=1,
            teacher_id=UUID(int=1),
            subject_id=1,
            starts_at=datetime(2026, 11, 30, 4, 0, tzinfo=UTC),
            ends_at=datetime(2026, 12, 1, 4, 45, tzinfo=UTC),
        )


def test_reschedule_rejects_off_grid_time_without_changing_lesson() -> None:
    starts_at = datetime(2026, 9, 10, 4, 0, tzinfo=UTC)
    ends_at = datetime(2026, 9, 10, 4, 45, tzinfo=UTC)
    lesson = Lesson.create(
        class_id=1,
        teacher_id=UUID(int=1),
        subject_id=1,
        starts_at=starts_at,
        ends_at=ends_at,
    )

    with pytest.raises(InvalidSchoolPeriod):
        lesson.reschedule(
            starts_at=datetime(2026, 9, 10, 5, 45, tzinfo=UTC),
            ends_at=datetime(2026, 9, 10, 6, 30, tzinfo=UTC),
        )

    assert (lesson.starts_at, lesson.ends_at) == (starts_at, ends_at)
