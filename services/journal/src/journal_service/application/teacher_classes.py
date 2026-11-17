"""Назначение преподавателей классам и чтение текущих назначений."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from journal_service.application.classes import ClassResult
from journal_service.application.ports.errors import (
    ClassNotFoundError,
    InvalidTeacherError,
    TeacherAlreadyAssignedError,
    TeacherNotFoundError,
)
from journal_service.application.ports.gateway_user_reader import GatewayUserReader
from journal_service.application.ports.unit_of_work import UnitOfWork


class AssignTeacherToClassCommand(BaseModel):
    """Проверенная пара преподавателя и школьного класса."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    teacher_id: UUID
    class_id: int = Field(ge=1, le=2147483647)


class UnassignTeacherFromClassCommand(BaseModel):
    """Пара для удаления, не требующая активности пользователя Gateway."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    teacher_id: UUID
    class_id: int = Field(ge=1, le=2147483647)


class AssignTeacherToClassResult(BaseModel):
    """Отличает новое назначение от идемпотентного повтора."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    created: bool


class ListClassesForTeacherQuery(BaseModel):
    """Проверенные параметры страницы назначений преподавателя."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    teacher_id: UUID
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2**63 - 1)


class AssignTeacherToClassHandler:
    """Проверяет пользователя у владельца и сохраняет уникальное назначение."""

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], user_reader: GatewayUserReader
    ) -> None:
        """Сохраняет зависимости без открытия соединений.

        Args:
            uow_factory: Фабрика транзакции Journal.
            user_reader: Авторитетное чтение роли и активности из Gateway.
        """
        self._uow_factory = uow_factory
        self._user_reader = user_reader

    async def handle(
        self, command: AssignTeacherToClassCommand
    ) -> AssignTeacherToClassResult:
        """Назначает активного teacher; повтор той же пары возвращает успех.

        Args:
            command: Проверенные ID преподавателя и класса.

        Returns:
            Признак создания новой связи.

        Raises:
            TeacherNotFoundError: Gateway подтвердил отсутствие пользователя.
            InvalidTeacherError: Пользователь не активный преподаватель.
            ClassNotFoundError: Класса нет в Journal.
            UserLookupUnavailableError: Gateway не дал достоверного ответа.
        """
        user = await self._user_reader.get_user(command.teacher_id)
        if user is None:
            raise TeacherNotFoundError
        if not user.is_active or user.role != "teacher":
            raise InvalidTeacherError
        try:
            async with self._uow_factory() as uow:
                if await uow.classes.get_class_by_id(command.class_id) is None:
                    raise ClassNotFoundError
                await uow.teacher_classes.add(command.teacher_id, command.class_id)
        except TeacherAlreadyAssignedError:
            # UoW уже откатил неудачную вставку; новая запись не нужна.
            return AssignTeacherToClassResult(created=False)
        return AssignTeacherToClassResult(created=True)


class UnassignTeacherFromClassHandler:
    """Снимает назначение без зависимости от доступности Gateway."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет фабрику транзакций.

        Args:
            uow_factory: Фабрика Unit of Work Journal.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: UnassignTeacherFromClassCommand) -> None:
        """Удаляет пару; отсутствие уже удалённой связи считается успехом.

        Args:
            command: Пара преподавателя и класса.
        """
        async with self._uow_factory() as uow:
            await uow.teacher_classes.remove(command.teacher_id, command.class_id)


class ListClassesForTeacherHandler:
    """Читает текущие назначения, не выдавая права по устаревшему профилю."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет фабрику отдельной транзакции чтения.

        Args:
            uow_factory: Фабрика Unit of Work Journal.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: ListClassesForTeacherQuery) -> list[ClassResult]:
        """Возвращает классы в порядке репозитория; профиль не проверяет.

        Args:
            query: UUID преподавателя и параметры страницы.

        Returns:
            Классы; пустой список для отсутствующих назначений.
        """
        async with self._uow_factory() as uow:
            classes = await uow.teacher_classes.list_classes_for_teacher(
                query.teacher_id, query.limit, query.offset
            )
            return [
                ClassResult(
                    id=x.id,
                    name=x.name,
                    study_year=x.study_year,
                    created_at=x.created_at,
                )
                for x in classes
            ]
