"""Интервальное чтение календаря без привязки к полуночи UTC."""

from datetime import timedelta
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.lesson import Lesson


class CalendarLessonsQuery(BaseModel):
    """Один доверенный владелец календаря и ограниченный полуоткрытый интервал."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    class_id: int | None = Field(default=None, ge=1, le=2147483647)
    teacher_id: UUID | None = None
    starts_at_from: AwareDatetime
    starts_at_until: AwareDatetime

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        """Требует ровно один фильтр и положительный интервал не более32суток."""
        if (self.class_id is None) == (self.teacher_id is None):
            raise ValueError("Specify exactly one calendar owner")
        if (
            not timedelta(0)
            < self.starts_at_until - self.starts_at_from
            <= timedelta(days=32)
        ):
            raise ValueError("Invalid calendar period")
        return self


class CalendarPeriodTooLargeError(Exception):
    """Слишком много уроков; вызывающий должен сузить период, а не потерять строки."""


class ListCalendarLessonsHandler:
    """Возвращает все уроки ограниченного периода либо явный отказ без усечения."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def handle(self, query: CalendarLessonsQuery) -> list[Lesson]:
        """Читает плановые и отменённые уроки в одной короткой SQL-транзакции."""
        async with self._uow_factory() as uow:
            lessons = await uow.lessons.list_calendar_lessons(**query.model_dump())
        if len(lessons) > 1000:
            raise CalendarPeriodTooLargeError
        return lessons
