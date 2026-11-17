"""Чтение авторитетного расписания конкретного преподавателя."""

from datetime import date
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.lesson import Lesson


class TeacherLessonDates(BaseModel):
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


class ListTeacherLessonsQuery(TeacherLessonDates):
    """Диапазон и UUID преподавателя из доверенного контекста."""

    teacher_id: UUID


class ListTeacherLessonsHandler:
    """Читает свои уроки без кеша и без изменения данных."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work Schedule.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: ListTeacherLessonsQuery) -> list[Lesson]:
        """Возвращает уроки, включая отменённые, по времени и ID.

        Args:
            query: UUID преподавателя и проверенные даты.

        Returns:
            Уроки преподавателя или пустой список.
        """
        async with self._uow_factory() as uow:
            return await uow.lessons.list_for_teacher(
                teacher_id=query.teacher_id,
                date_from=query.date_from,
                date_to=query.date_to,
            )
