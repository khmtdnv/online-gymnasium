"""Проверка оплаты до обращения к учебным материалам."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from gateway_service.api.security import get_authenticated_user
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.domain.user import Role
from gateway_service.infrastructure.billing_client import BillingRequestError
from gateway_service.infrastructure.journal_client import JournalUnavailableError


async def check_student_tuition(app, user: GetCurrentUserResult) -> None:
    """Не смешивает подтверждённую задолженность со сбоем Billing."""
    if user.role != Role.STUDENT or not app.state.settings.enforce_tuition_access:
        return
    journal = app.state.journal_client
    if journal is None:
        raise HTTPException(503, "Journal unavailable")
    try:
        if await journal.get_current_class_id(user.id) is None:
            return
    except JournalUnavailableError as exc:
        raise HTTPException(503, "Journal unavailable") from exc
    client = app.state.billing_client
    if client is None:
        raise HTTPException(503, "Billing unavailable")
    try:
        allowed = await client.quarter_access(user.id)
    except BillingRequestError as exc:
        raise HTTPException(503, "Billing unavailable") from exc
    if not allowed:
        raise HTTPException(403, "Tuition payment required")


async def require_learning_access(
    request: Request,
    user: Annotated[GetCurrentUserResult, Depends(get_authenticated_user)],
) -> None:
    """Применяет ограничение к учебной HTTP-ручке после авторизации."""
    await check_student_tuition(request.app, user)
