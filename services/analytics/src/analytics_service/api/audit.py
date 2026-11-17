"""Служебные read-only маршруты; публичные роли проверяет Gateway."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from analytics_service.application.audit import (
    AuditEvent,
    AuditQuery,
    ProgressQuery,
    ProgressRow,
)

bearer = HTTPBearer(auto_error=False)


def require_gateway(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    """Закрывает чтение при отсутствующем или неверном отдельном read-секрете."""
    expected = request.app.state.audit_service_token
    if not expected or request.app.state.audit_repository_factory is None:
        raise HTTPException(503, "Audit integration unavailable")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(
            401, "Invalid service token", headers={"WWW-Authenticate": "Bearer"}
        )


router = APIRouter(
    prefix="/internal", dependencies=[Depends(require_gateway)], include_in_schema=False
)


@router.get("/audit", response_model=list[AuditEvent])
async def audit_events(
    request: Request, response: Response, query: Annotated[AuditQuery, Query()]
) -> list[AuditEvent]:
    """Возвращает только запрошенную страницу подтверждённых событий."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await request.app.state.audit_repository_factory().list_events(query)
    except Exception as exc:
        raise HTTPException(503, "Audit storage unavailable") from exc


@router.get("/progress", response_model=list[ProgressRow])
async def progress(
    request: Request, response: Response, query: Annotated[ProgressQuery, Query()]
) -> list[ProgressRow]:
    """Возвращает исторические оценки класса, не текущее членство учеников."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await request.app.state.audit_repository_factory().get_progress(query)
    except ValueError as exc:
        raise HTTPException(422, "Narrow the report period") from exc
    except Exception as exc:
        raise HTTPException(503, "Progress storage unavailable") from exc
