"""Авторитетные чтения уроков для проверки домашнего задания."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schedule_service.application.errors import LessonNotFound
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.lesson import Lesson


class LookupHomeworkLessonsQuery(BaseModel):
    """Ограниченный пакет уникальных ID, без чтения всего расписания."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson_ids: list[Annotated[int, Field(strict=True, ge=1, le=2147483647)]] = Field(
        min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        """Отклоняет повторяющиеся ссылки внутри одного пакета."""
        if len(set(self.lesson_ids)) != len(self.lesson_ids):
            raise ValueError("Lesson IDs must be unique")
        return self


class LookupHomeworkLessonsHandler:
    """Читает пакет напрямую у владельца в одной локальной транзакции."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика UoW Schedule.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: LookupHomeworkLessonsQuery) -> list[Lesson]:
        """Возвращает существующие уроки; отсутствующие ID пропускаются.

        Args:
            query: Проверенный пакет ID.

        Returns:
            Уроки по возрастанию ID, включая отменённые.
        """
        async with self._uow_factory() as uow:
            return await uow.lessons.get_many(query.lesson_ids)


class GetHomeworkLessonQuery(BaseModel):
    """ID урока, запрошенного Homework, без прав из пользовательского ввода."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson_id: int = Field(strict=True, ge=1, le=2147483647)


class GetHomeworkLessonHandler:
    """Читает урок без использования Redis-копии расписания."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет фабрику локальной транзакции.

        Args:
            uow_factory: Новая сессия на запрос.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: GetHomeworkLessonQuery) -> Lesson:
        """Возвращает исходный урок, включая статус отмены.

        Args:
            query: Проверенный ID урока.

        Returns:
            Авторитетные данные урока.

        Raises:
            LessonNotFound: Урок отсутствует.
        """
        async with self._uow_factory() as uow:
            lesson = await uow.lessons.get(query.lesson_id)
            if lesson is None:
                raise LessonNotFound
        return lesson


class GetNextHomeworkLessonHandler:
    """Предлагает следующий урок, не назначая срок за пользователя."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет фабрику локальной транзакции.

        Args:
            uow_factory: Новая сессия на запрос.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: GetHomeworkLessonQuery) -> Lesson | None:
        """Отличает отсутствие исходного урока от отсутствия кандидата.

        Args:
            query: Проверенный ID исходного урока.

        Returns:
            Ближайший плановый урок того же класса/предмета либо None.

        Raises:
            LessonNotFound: Исходный урок не существует.
        """
        async with self._uow_factory() as uow:
            source = await uow.lessons.get(query.lesson_id)
            if source is None:
                raise LessonNotFound
            return await uow.lessons.get_next_lesson(
                class_id=source.class_id,
                subject_id=source.subject_id,
                after=source.starts_at,
            )
