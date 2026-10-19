"""Проверенный контракт чтения авторитетных уроков Schedule."""

from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


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


class ScheduleReader(Protocol):
    """Не смешивает отсутствие урока со сбоем его владельца."""

    async def get_lessons(self, lesson_ids: list[int]) -> dict[int, LessonInfo]:
        """Получает точный пакет уроков одним запросом.

        Args:
            lesson_ids: Уникальные ID сохранённых сроков.

        Returns:
            Проверенные уроки по ID.

        Raises:
            OwnerLookupUnavailableError: Пакет неполон, некорректен или недоступен.
        """
        ...

    async def get_lesson(self, lesson_id: int) -> LessonInfo | None:
        """Читает урок по ID.

        Args:
            lesson_id: ID урока из Schedule.

        Returns:
            Урок либо None при подтверждённом отсутствии.

        Raises:
            OwnerLookupUnavailableError: Запрос/контракт не позволил прочитать урок.
        """
        ...

    async def get_next_lesson(self, lesson_id: int) -> LessonInfo | None:
        """Читает предложение следующего урока по исходному.

        Args:
            lesson_id: ID существующего исходного урока.

        Returns:
            Подходящий урок либо None при подтверждённом пустом поиске.

        Raises:
            OwnerLookupUnavailableError: Исходный урок исчез или запрос некорректен.
        """
        ...
