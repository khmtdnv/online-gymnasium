"""Доступ к файлам только через доверенный Gateway, не по знанию UUID."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def require_gateway(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Проверяет отдельный служебный секрет; пустая настройка запрещает доступ."""
    token = request.app.state.settings.gateway_service_token
    if (
        not token
        or credentials is None
        or not secrets.compare_digest(credentials.credentials.encode(), token.encode())
    ):
        raise HTTPException(
            401, "Invalid service credentials", headers={"WWW-Authenticate": "Bearer"}
        )


def get_creator(
    actor_id: Annotated[UUID, Header(alias="X-Actor-ID")],
    _: Annotated[None, Depends(require_gateway)],
) -> UUID:
    """UUID сотрудника задан Gateway после JWT, не формой создания документа."""
    return actor_id
