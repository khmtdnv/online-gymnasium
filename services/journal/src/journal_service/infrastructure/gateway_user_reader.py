"""Чтение минимальных данных пользователя через HTTP API Gateway."""

from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from journal_service.application.ports.errors import UserLookupUnavailableError
from journal_service.application.ports.gateway_user_reader import (
    GatewayUserInfo,
    GatewayUserRole,
)


class GatewayUserResponse(BaseModel):
    """Проверяет ответ Gateway, не преобразуя строки и числа в boolean."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    role: GatewayUserRole
    is_active: StrictBool


class HttpGatewayUserReader:
    """Читает пользователя по HTTP; переданный клиент закрывает вызывающий код."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Сохраняет клиент с base_url Gateway и отдельный служебный секрет.

        Args:
            http_client: Уже настроенный AsyncClient, принадлежащий вызывающему.
            service_token: Секрет Journal для чтения пользователей Gateway.
        """
        self._http_client = http_client
        self._service_token = service_token

    async def get_user(self, user_id: UUID) -> GatewayUserInfo | None:
        """Запрашивает пользователя без проверки бизнес-правил Journal.

        Args:
            user_id: ID пользователя, который должен совпасть с ID в ответе.

        Returns:
            Проверенные данные пользователя либо None при HTTP 404.

        Raises:
            UserLookupUnavailableError: Сбой сети, статуса или контракта ответа.
        """
        try:
            response = await self._http_client.get(
                f"/internal/users/{user_id}",
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                return None

            if response.status_code != 200:
                raise UserLookupUnavailableError

            user = GatewayUserResponse.model_validate_json(response.content)

        except (httpx.HTTPError, ValidationError) as exc:
            raise UserLookupUnavailableError from exc

        if user.id != user_id:
            raise UserLookupUnavailableError

        return GatewayUserInfo(id=user.id, role=user.role, is_active=user.is_active)
