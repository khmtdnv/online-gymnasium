"""Чтение минимальных данных пользователя для других сервисов."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from gateway_service.application.errors import UserNotFoundError
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.domain.user import Role


class GetUserQuery(BaseModel):
    """Запрашивает пользователя по его ID из Gateway."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    user_id: UUID


class UserLookupResult(BaseModel):
    """Данные для проверки пользователя без email, пароля и токенов."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: UUID
    role: Role
    is_active: bool


class GetUserHandler:
    """Читает пользователя, не решая правила доступа другого сервиса."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет фабрику транзакционного контекста.

        Args:
            uow_factory: Фабрика отдельного Unit of Work для чтения.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: GetUserQuery) -> UserLookupResult:
        """Возвращает роль и активность существующего пользователя.

        Args:
            query: ID пользователя, которого нужно прочитать.

        Returns:
            Минимальные данные пользователя любой роли и активности.

        Raises:
            UserNotFoundError: Пользователя нет в Gateway.
        """
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(query.user_id)
            if user is None:
                raise UserNotFoundError
            result = UserLookupResult(
                id=user.id, role=user.role, is_active=user.is_active
            )
        return result
