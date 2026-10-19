"""Контракты Gateway для выдачи ДЗ без зависимости от пакета Homework."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PositiveId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Description = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=10000,
    ),
]


class CreateHomeworkRequest(BaseModel):
    """Вход преподавателя: только описание и один из способов срока."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    description: Description
    due_lesson_id: PositiveId | None = None
    manual_due_datetime: AwareDatetime | None = None

    @field_validator("manual_due_datetime", mode="before")
    @classmethod
    def validate_iso_deadline(cls, value: object) -> datetime | None:
        """Принимает ISO-дату, но не неявный числовой Unix timestamp.

        Args:
            value: Дата из JSON либо уже разобранное datetime.

        Returns:
            Дата для последующей проверки часового смещения.

        Raises:
            ValueError: Значение не является ISO-датой или datetime.
        """
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        if value is None or isinstance(value, datetime):
            return value
        raise ValueError("Expected an ISO datetime with timezone")

    @model_validator(mode="after")
    def validate_due_mode(self) -> Self:
        """Отклоняет отсутствие срока или одновременную передачу двух сроков."""
        if (self.due_lesson_id is None) == (self.manual_due_datetime is None):
            raise ValueError("Exactly one due mode is required")
        return self


class HomeworkResult(BaseModel):
    """Строго проверенный успешный ответ владельца заданий."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    id: PositiveId
    issued_lesson_id: PositiveId
    class_id: PositiveId
    subject_id: PositiveId
    author_id: UUID
    description: Description
    due_lesson_id: PositiveId | None
    manual_due_datetime: AwareDatetime | None
    created_at: AwareDatetime


class HomeworkRequestError(Exception):
    """Homework подтвердил известный бизнес-отказ, а не сбой связи."""

    def __init__(self, status_code: int, code: str) -> None:
        """Сохраняет только распознанные клиентом статус и код.

        Args:
            status_code: Статус бизнес-отказа.
            code: Машиночитаемый код без сырого сообщения владельца.
        """
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class HomeworkUnavailableError(Exception):
    """Результат выдачи неизвестен из-за сбоя связи или внешнего контракта."""


class StudentHomeworkResult(HomeworkResult):
    """Проверяет вычисленный срок чтения, не нормализуя ответ владельца."""

    description: str = Field(strict=True, min_length=1, max_length=10000)
    final_due_datetime: AwareDatetime | None
    due_status: Literal["manual", "lesson", "lesson_cancelled"]

    @field_validator("description")
    @classmethod
    def validate_canonical_description(cls, value: str) -> str:
        """Не скрывает лишние краевые пробелы успешного ответа."""
        if value != value.strip():
            raise ValueError("Description must already be normalized")
        return value

    @model_validator(mode="after")
    def validate_deadline(self) -> Self:
        """Проверяет XOR сроков и согласованность вычисленных полей."""
        if (self.due_lesson_id is None) == (self.manual_due_datetime is None):
            raise ValueError("Exactly one due mode is required")
        if self.manual_due_datetime is not None:
            valid = (
                self.due_status == "manual"
                and self.final_due_datetime == self.manual_due_datetime
            )
        else:
            valid = (
                self.due_status == "lesson"
                and self.final_due_datetime is not None
                or self.due_status == "lesson_cancelled"
                and self.final_due_datetime is None
            )
        if not valid:
            raise ValueError("Deadline state is inconsistent")
        return self
