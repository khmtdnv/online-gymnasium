"""Проверенные данные событий Homework без текста ответов и файлов."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ReviewedAnswerPayload(BaseModel):
    """Исторические ссылки и результат одной проверки, не текущий состав класса."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    answer_id: int = Field(ge=1, le=2147483647)
    homework_id: int = Field(ge=1, le=2147483647)
    student_id: UUID
    class_id: int = Field(ge=1, le=2147483647)
    subject_id: int = Field(ge=1, le=2147483647)
    teacher_id: UUID
    status: Literal["returned", "graded"]
    grade: int | None = Field(ge=2, le=5)

    @model_validator(mode="after")
    def valid_grade(self) -> Self:
        """Возврат не является оценкой; проверенная работа должна иметь оценку."""
        if (self.status == "graded") != (self.grade is not None):
            raise ValueError("Grade does not match review status")
        return self


class EventActor(BaseModel):
    """UUID преподавателя Gateway, не ID сотрудника Django."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    source: Literal["gateway"] = "gateway"
    id: UUID


class ReviewedAnswerEvent(BaseModel):
    """Версионированный конверт для общей очереди и будущего consumer."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    event_id: UUID
    event_source: Literal["homework"] = "homework"
    event_type: Literal["homework.answer.reviewed"] = "homework.answer.reviewed"
    schema_version: Literal[1] = 1
    occurred_at: AwareDatetime
    request_id: str | None = None
    actor: EventActor
    payload: ReviewedAnswerPayload
