"""Проверка пользователя и серверной сессии для доверенного Backoffice."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from gateway_service.api.dependencies import require_backoffice_service_token
from gateway_service.api.security import get_authenticated_user
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.domain.user import Role

router = APIRouter(
    prefix="/internal/backoffice",
    dependencies=[Depends(require_backoffice_service_token)],
    include_in_schema=False,
)


class BackofficeIdentity(BaseModel):
    """Подтверждённые идентификаторы учётной записи и серверной сессии."""

    user_id: UUID
    session_id: UUID


class BackofficeSessionCheck(BaseModel):
    """Пара идентификаторов, которую проверяет доверенный Backoffice."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    session_id: UUID


@router.get("/identity", response_model=BackofficeIdentity)
async def get_backoffice_identity(
    response: Response,
    user: Annotated[GetCurrentUserResult, Depends(get_authenticated_user)],
) -> BackofficeIdentity:
    """Разрешает вход только активному администратору с новой сессией."""
    response.headers["Cache-Control"] = "private, no-store"
    if user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )
    if user.session_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session required"
        )
    return BackofficeIdentity(user_id=user.id, session_id=user.session_id)


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
async def check_backoffice_session(
    body: BackofficeSessionCheck, request: Request
) -> Response:
    """Проверяет сессию и актуальные права пользователя без передачи JWT."""
    async with request.app.state.uow_factory() as uow:
        user = await uow.users.get_by_id(body.user_id)
        if (
            user is None
            or not user.is_active
            or user.role != Role.ADMIN
            or not await uow.auth_sessions.is_active(body.session_id, body.user_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid"
            )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/session/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_backoffice_session(
    body: BackofficeSessionCheck, request: Request
) -> Response:
    """Отзывает общую сессию при выходе из Backoffice."""
    async with request.app.state.uow_factory() as uow:
        await uow.auth_sessions.revoke(body.session_id, body.user_id)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "private, no-store"},
    )
