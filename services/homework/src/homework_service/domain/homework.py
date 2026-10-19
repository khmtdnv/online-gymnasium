"""Домашнее задание и правила, проверяемые без внешних запросов."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class Homework:
    """Задание из урока с одним из двух способов указания срока."""

    issued_lesson_id: int
    class_id: int
    subject_id: int
    author_id: UUID
    description: str
    due_lesson_id: int | None = None
    manual_due_datetime: datetime | None = None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Проверяет локальные значения, но не права и состояние чужих сервисов.

        Raises:
            ValueError: Некорректные ID, описание, автор или способ срока.
        """
        for value in (self.issued_lesson_id, self.class_id, self.subject_id):
            self._validate_id(value)
        for value in (self.id, self.due_lesson_id):
            if value is not None:
                self._validate_id(value)
        if not isinstance(self.author_id, UUID):
            raise ValueError("author_id must be a UUID")  # noqa: TRY004 — общий контракт доменной валидации
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")  # noqa: TRY004 — общий контракт доменной валидации
        self.description = self.description.strip()
        if not 1 <= len(self.description) <= 10000:
            raise ValueError("description must contain 1 to 10000 characters")
        if (self.due_lesson_id is None) == (self.manual_due_datetime is None):
            raise ValueError("Exactly one due mode is required")
        for value in (self.manual_due_datetime, self.created_at):
            if value is not None and (
                not isinstance(value, datetime) or value.utcoffset() is None
            ):
                raise ValueError("Datetime must have a known UTC offset")

    @staticmethod
    def _validate_id(value: int) -> None:
        """Проверяет диапазон PostgreSQL INTEGER без допуска bool.

        Args:
            value: Проверяемый идентификатор.

        Raises:
            ValueError: Значение не положительный INTEGER.
        """
        if type(value) is not int or not 1 <= value <= 2147483647:
            raise ValueError("ID must be a positive PostgreSQL INTEGER")
