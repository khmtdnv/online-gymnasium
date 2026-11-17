"""Административный отчёт и общий аудит через проверенный Gateway."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import TypeAdapter
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import RequireRoles
from gateway_service.application.analytics import (
    AuditEvent,
    AuditQuery,
    NamedProgressRow,
    ProgressQuery,
    ProgressRow,
)
from gateway_service.application.teacher_lessons import ScheduleUnavailableError
from gateway_service.domain.user import Role
from gateway_service.infrastructure.analytics_client import (
    AnalyticsQueryTooLargeError,
    AnalyticsUnavailableError,
)
from gateway_service.infrastructure.journal_client import (
    ClassNameResponse,
    JournalUnavailableError,
)

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["analytics"],
    dependencies=[Depends(RequireRoles((Role.ADMIN,)))],
)


def get_client(request: Request):
    """Отсутствие настройки означает503, не пустые данные."""
    client = request.app.state.analytics_client
    if client is None:
        raise HTTPException(503, "Analytics unavailable")
    return client


@router.get("/progress", response_model=list[NamedProgressRow])
async def progress(
    request: Request, response: Response, query: Annotated[ProgressQuery, Query()]
) -> list[NamedProgressRow]:
    """Дополняет весь отчёт одним SQL-пакетом ФИО и одним HTTP-пакетом предметов."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        rows = TypeAdapter(list[ProgressRow]).validate_python(
            await get_client(request).get_progress(query)
        )
        if not rows:
            return []
        if request.app.state.schedule_client is None:
            raise HTTPException(503, "Schedule unavailable")
        subjects = await request.app.state.schedule_client.get_subject_names(
            list({row.subject_id for row in rows})
        )
        async with request.app.state.uow_factory() as uow:
            users = await uow.users.get_by_ids(list({row.student_id for row in rows}))
        names = {
            user.id: " ".join(
                part
                for part in (user.last_name, user.first_name, user.middle_name)
                if part
            )
            for user in users
        }
        return [
            NamedProgressRow(
                **row.model_dump(),
                student_name=names.get(row.student_id) or "Пользователь недоступен",
                subject_name=subjects.get(row.subject_id)
                or "Название предмета не задано",
            )
            for row in rows
        ]
    except AnalyticsQueryTooLargeError as exc:
        raise HTTPException(422, "Narrow the report period") from exc
    except (
        AnalyticsUnavailableError,
        ScheduleUnavailableError,
        SQLAlchemyError,
    ) as exc:
        raise HTTPException(503, "Analytics unavailable") from exc


@router.get("/audit", response_model=list[AuditEvent])
async def audit_events(
    request: Request, response: Response, query: Annotated[AuditQuery, Query()]
) -> list[AuditEvent]:
    """Не раскрывает служебные credentials и не позволяет читать журнал другим ролям."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await get_client(request).list_events(query)
    except AnalyticsQueryTooLargeError as exc:
        raise HTTPException(422, "Narrow the audit period") from exc
    except AnalyticsUnavailableError as exc:
        raise HTTPException(503, "Analytics unavailable") from exc


@router.get("/classes", response_model=list[ClassNameResponse])
async def classes(
    request: Request,
    response: Response,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> list[ClassNameResponse]:
    """Страница100 названий для выбора класса, не список всех учеников."""
    response.headers["Cache-Control"] = "private, no-store"
    client = request.app.state.journal_client
    if client is None:
        raise HTTPException(503, "Journal unavailable")
    try:
        return await client.list_classes(limit=100, offset=offset)
    except JournalUnavailableError as exc:
        raise HTTPException(503, "Journal unavailable") from exc
