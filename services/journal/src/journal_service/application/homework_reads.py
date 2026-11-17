"""Чтение конкретного назначения для внешней проверки прав Homework."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from journal_service.application.ports.unit_of_work import UnitOfWork


class TeacherClassQuery(BaseModel):
    """Проверенные ссылки на учителя и класс."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    teacher_id: UUID
    class_id: int = Field(strict=True, ge=1, le=2147483647)


class CheckTeacherClassHandler:
    """Подтверждает только наличие назначения, не статус аккаунта Gateway."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет фабрику локальной транзакции.

        Args:
            uow_factory: Фабрика отдельного UoW на запрос.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: TeacherClassQuery) -> bool:
        """Читает назначение из авторитетной базы Journal.

        Args:
            query: Проверенная пара идентификаторов.

        Returns:
            True для существующей пары; False для подтверждённого отсутствия.
        """
        async with self._uow_factory() as uow:
            return await uow.teacher_classes.is_assigned(
                query.teacher_id, query.class_id
            )
