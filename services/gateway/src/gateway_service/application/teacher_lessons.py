"""Проверенные контракты расписания и карточки без импорта других сервисов."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from gateway_service.application.homework import StudentHomeworkResult


class LessonInfo(BaseModel):
    """Урок без неявного приведения чисел и неизвестных статусов."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: int = Field(ge=1, le=2147483647)
    class_id: int = Field(ge=1, le=2147483647)
    subject_id: int = Field(ge=1, le=2147483647)
    teacher_id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: Literal["planned", "canceled"]
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Запрещает пустой или обратный интервал внешнего ответа.

        Returns:
            Проверенный урок.

        Raises:
            ValueError: Начало не раньше конца.
        """
        if self.starts_at >= self.ends_at:
            raise ValueError("Lesson must start before it ends")
        return self


class ListTeacherLessonsQuery(BaseModel):
    """Даты включительно, максимум семь календарных дней UTC."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """Отклоняет обратный диапазон и непредставимую правую границу."""
        if (
            not 0 <= (self.date_to - self.date_from).days <= 6
            or self.date_to == date.max
        ):
            raise ValueError("Expected one to seven calendar days")
        return self


class TeacherLessonResult(BaseModel):
    """Открытый урок, следующий кандидат и две непересекающиеся группы ДЗ."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson: LessonInfo
    next_lesson: LessonInfo | None
    homework_for_lesson: list[StudentHomeworkResult]
    homework_from_lesson: list[StudentHomeworkResult]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Проверяет связи карточки без дополнительных сетевых запросов."""
        if self.next_lesson is not None and (
            self.lesson.status == "canceled"
            or self.next_lesson.class_id != self.lesson.class_id
            or self.next_lesson.subject_id != self.lesson.subject_id
            or self.next_lesson.starts_at <= self.lesson.starts_at
            or self.next_lesson.status != "planned"
        ):
            raise ValueError("Invalid next lesson")
        if len(self.homework_from_lesson) > 1:
            raise ValueError("Multiple assignments from one lesson")
        homeworks = self.homework_for_lesson + self.homework_from_lesson
        if len({row.id for row in homeworks}) != len(homeworks):
            raise ValueError("Duplicate homework")
        for group, from_lesson in (
            (self.homework_for_lesson, False),
            (self.homework_from_lesson, True),
        ):
            keys = [(row.created_at, row.id) for row in group]
            if keys != sorted(keys, reverse=True):
                raise ValueError("Invalid homework order")
            for row in group:
                if (
                    row.class_id != self.lesson.class_id
                    or row.subject_id != self.lesson.subject_id
                    or (row.issued_lesson_id if from_lesson else row.due_lesson_id)
                    != self.lesson.id
                ):
                    raise ValueError("Incompatible homework reference")
                if not from_lesson and (
                    row.due_status
                    != (
                        "lesson"
                        if self.lesson.status == "planned"
                        else "lesson_cancelled"
                    )
                    or row.final_due_datetime
                    != (
                        self.lesson.starts_at
                        if self.lesson.status == "planned"
                        else None
                    )
                ):
                    raise ValueError("Homework deadline differs from included lesson")
        return self


class ScheduleUnavailableError(Exception):
    """Schedule недоступен либо вернул ответ, нарушающий ожидаемый контракт."""
