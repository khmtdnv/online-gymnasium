"""Проверяет данные периода членства и вычисляемое состояние."""

from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from uuid import uuid4

import pytest


def test_new_class_period_has_no_server_fields() -> None:
    """До сохранения хранит ученика и класс без выдуманных ID и времени."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    student_id = uuid4()
    class_period = StudentClassPeriod(student_id=student_id, class_id=10)

    assert class_period.student_id == student_id
    assert class_period.class_id == 10
    assert class_period.id is None
    assert class_period.joined_at is None
    assert class_period.left_at is None
    assert class_period.is_active is True


def test_class_period_activity_follows_end_of_period() -> None:
    """Вычисляет состояние по left_at, а не хранит отдельный устаревающий флаг."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    left_at = datetime(2026, 10, 12, 10, tzinfo=UTC)
    class_period = StudentClassPeriod(
        student_id=uuid4(), class_id=10, id=42, joined_at=joined_at
    )

    assert class_period.id == 42
    assert class_period.joined_at == joined_at
    assert class_period.is_active is True

    class_period.left_at = left_at

    assert class_period.left_at == left_at
    assert class_period.is_active is False


@pytest.mark.parametrize("class_id", [0, -1])
def test_rejects_nonpositive_class_id(class_id: int) -> None:
    """Не создаёт членство со ссылкой на неположительный ID класса."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    with pytest.raises(ValueError):
        StudentClassPeriod(student_id=uuid4(), class_id=class_id)


def test_accepts_smallest_positive_class_id() -> None:
    """Разрешает положительный ID начиная с единицы."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    class_period = StudentClassPeriod(student_id=uuid4(), class_id=1)

    assert class_period.class_id == 1


def test_rejects_end_without_start() -> None:
    """Не позволяет завершить период без известного времени вступления."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    with pytest.raises(ValueError):
        StudentClassPeriod(
            student_id=uuid4(),
            class_id=10,
            left_at=datetime(2026, 10, 12, 10, tzinfo=UTC),
        )


def test_closed_class_period_is_not_active() -> None:
    """Разрешает завершённый период, если время вступления тоже задано."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    left_at = datetime(2026, 10, 12, 10, tzinfo=UTC)
    class_period = StudentClassPeriod(
        student_id=uuid4(), class_id=10, joined_at=joined_at, left_at=left_at
    )

    assert class_period.joined_at == joined_at
    assert class_period.left_at == left_at
    assert class_period.is_active is False


@pytest.mark.parametrize("field", ["joined_at", "left_at"])
def test_rejects_naive_timestamps(field: str) -> None:
    """Не принимает заданное время без информации о смещении UTC."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    values = {
        "joined_at": datetime(2026, 9, 1, 9, tzinfo=UTC),
        "left_at": datetime(2026, 10, 12, 10, tzinfo=UTC),
    }
    values[field] = datetime.combine(
        date(2026, 9, 1), time(9)
    )  # намеренно неверное время

    with pytest.raises(ValueError):
        StudentClassPeriod(student_id=uuid4(), class_id=10, **values)


class NoOffsetTimezone(tzinfo):
    """Имитирует tzinfo, не определяющий смещение для переданного времени."""

    def utcoffset(self, dt: datetime | None) -> None:
        """Сообщает, что смещение UTC для даты неизвестно."""
        return


@pytest.mark.parametrize("field", ["joined_at", "left_at"])
def test_rejects_tzinfo_with_no_offset(field: str) -> None:
    """Проверяет смещение, а не только наличие объекта tzinfo."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    values = {
        "joined_at": datetime(2026, 9, 1, 9, tzinfo=UTC),
        "left_at": datetime(2026, 10, 12, 10, tzinfo=UTC),
    }
    values[field] = datetime(2026, 9, 1, 9, tzinfo=NoOffsetTimezone())

    with pytest.raises(ValueError):
        StudentClassPeriod(student_id=uuid4(), class_id=10, **values)


@pytest.mark.parametrize("zone", [UTC, timezone(timedelta(hours=3))])
def test_accepts_aware_timestamps(zone: tzinfo) -> None:
    """Принимает UTC с нулевым смещением и другие известные смещения."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    joined_at = datetime(2026, 9, 1, 9, tzinfo=zone)
    class_period = StudentClassPeriod(
        student_id=uuid4(), class_id=10, joined_at=joined_at
    )

    assert class_period.joined_at == joined_at
    assert class_period.is_active is True


@pytest.mark.parametrize(
    "left_at",
    [
        datetime(2026, 10, 12, 9, tzinfo=UTC),
        datetime(2026, 10, 12, 12, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_rejects_end_before_start_as_actual_instant(left_at):
    """Сравнивает моменты времени, а не показания часов в разных поясах."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    with pytest.raises(ValueError):
        StudentClassPeriod(
            student_id=uuid4(),
            class_id=10,
            joined_at=datetime(2026, 10, 12, 10, tzinfo=UTC),
            left_at=left_at,
        )


@pytest.mark.parametrize(
    "left_at",
    [
        datetime(2026, 10, 12, 10, tzinfo=UTC),
        datetime(2026, 10, 12, 13, tzinfo=timezone(timedelta(hours=3))),
    ],
)
def test_accepts_equal_class_period_instants(left_at):
    """Разрешает нулевой период даже при разных записях смещения."""
    from journal_service.domain.student_class_period import StudentClassPeriod

    class_period = StudentClassPeriod(
        student_id=uuid4(),
        class_id=10,
        joined_at=datetime(2026, 10, 12, 10, tzinfo=UTC),
        left_at=left_at,
    )
    assert not class_period.is_active
