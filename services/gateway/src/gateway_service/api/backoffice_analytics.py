"""Закрытые отчёты для административного интерфейса Backoffice."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from gateway_service.api.analytics import audit_events, classes, progress
from gateway_service.api.dependencies import require_backoffice_service_token
from gateway_service.application.analytics import (
    AuditEvent,
    AuditQuery,
    NamedProgressRow,
    ProgressQuery,
)
from gateway_service.infrastructure.journal_client import ClassNameResponse

router = APIRouter(
    prefix="/internal/backoffice/analytics",
    dependencies=[Depends(require_backoffice_service_token)],
    include_in_schema=False,
)


@router.get("/audit", response_model=list[AuditEvent])
async def get_audit(
    request: Request, response: Response, query: Annotated[AuditQuery, Query()]
) -> list[AuditEvent]:
    """Возвращает страницу журнала доверенному Backoffice."""
    return await audit_events(request, response, query)


@router.get("/progress", response_model=list[NamedProgressRow])
async def get_progress(
    request: Request, response: Response, query: Annotated[ProgressQuery, Query()]
) -> list[NamedProgressRow]:
    """Возвращает отчёт с именами учеников и предметов."""
    return await progress(request, response, query)


@router.get("/classes", response_model=list[ClassNameResponse])
async def get_classes(
    request: Request,
    response: Response,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> list[ClassNameResponse]:
    """Возвращает страницу классов для выбора отчёта."""
    return await classes(request, response, offset)
