from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


class DomainException(Exception):
    """Базовая ошибка бизнес-правила расписания."""


class InvalidLessonInterval(DomainException):
    """Время без смещения, начало не раньше конца или границы в разных днях."""


class LessonAlreadyCanceled(DomainException):
    """Урок уже отменён и не может быть отменён повторно."""


@dataclass
class Lesson:
    """Урок с интервалом, статусом и версией для проверки изменений."""

    class_id: int
    teacher_id: UUID
    subject_id: int
    starts_at: datetime
    ends_at: datetime
    id: int | None = None
    status: str = "planned"
    version: int = 1

    @staticmethod
    def _validate_interval(starts_at: datetime, ends_at: datetime) -> None:
        """Проверяет положительный интервал в пределах одного календарного дня.

        Args:
            starts_at: Дата и время начала урока.
            ends_at: Дата и время конца урока.

        Raises:
            InvalidLessonInterval: Время без известного смещения UTC, начало
                не раньше конца или даты границ различаются.
        """
        if any(
            not isinstance(value, datetime) or value.utcoffset() is None
            for value in (starts_at, ends_at)
        ):
            raise InvalidLessonInterval("Lesson times must have a known UTC offset")
        if (
            starts_at.astimezone(UTC) >= ends_at.astimezone(UTC)
            or starts_at.date() != ends_at.date()
        ):
            raise InvalidLessonInterval

    @staticmethod
    def create(
        class_id: int,
        teacher_id: UUID,
        subject_id: int,
        starts_at: datetime,
        ends_at: datetime,
    ) -> Lesson:
        """Создаёт плановый урок после проверки интервала.

        Args:
            class_id: ID класса, для которого выполняется операция.
            teacher_id: ID учителя урока.
            subject_id: ID учебного предмета.
            starts_at: Дата и время начала урока.
            ends_at: Дата и время конца урока.

        Returns:
            Новый урок без ID базы данных.

        Raises:
            InvalidLessonInterval: Интервал не укладывается в допустимый день.
        """
        if not isinstance(teacher_id, UUID):
            raise ValueError("teacher_id must be a UUID")  # noqa: TRY004 — доменный контракт ValueError
        Lesson._validate_interval(starts_at, ends_at)

        return Lesson(
            class_id=class_id,
            teacher_id=teacher_id,
            subject_id=subject_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def reschedule(self, starts_at: datetime, ends_at: datetime) -> None:
        """Меняет начало и конец урока после проверки интервала.

        Args:
            starts_at: Дата и время начала урока.
            ends_at: Дата и время конца урока.

        Raises:
            InvalidLessonInterval: Новый интервал недопустим.
        """
        Lesson._validate_interval(starts_at, ends_at)

        self.starts_at = starts_at
        self.ends_at = ends_at

    def cancel(self) -> None:
        """Меняет статус урока на canceled.

        Raises:
            LessonAlreadyCanceled: Урок уже отменён.
        """
        if self.status == "canceled":
            raise LessonAlreadyCanceled

        self.status = "canceled"
