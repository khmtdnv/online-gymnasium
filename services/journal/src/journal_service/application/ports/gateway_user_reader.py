"""Контракт чтения данных пользователя без зависимости от пакета Gateway."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

GatewayUserRole = Literal["student", "teacher", "parent", "admin"]


class GatewayUserInfo(BaseModel):
    """Минимальные данные для последующей проверки правил Journal."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: UUID
    role: GatewayUserRole
    is_active: bool


class GatewayUserReader(Protocol):
    """Получает пользователя у сервиса, который владеет учётными записями."""

    async def get_user(self, user_id: UUID) -> GatewayUserInfo | None:
        """Читает пользователя, отличая отсутствие от недоступности проверки.

        Args:
            user_id: ID пользователя из Gateway.

        Returns:
            Данные пользователя любой роли и активности либо None при 404.

        Raises:
            UserLookupUnavailableError: Нельзя получить достоверный ответ.
        """
        ...
