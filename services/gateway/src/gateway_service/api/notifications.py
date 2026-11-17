"""Личные уведомления всех активных ролей, адресат только из авторизации."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from gateway_service.api.security import get_authenticated_user
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.notifications import Notification, NotificationCount
from gateway_service.infrastructure.notification_client import NotificationRequestError

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
User = Annotated[GetCurrentUserResult, Depends(get_authenticated_user)]


class PageQuery(BaseModel):
    """Запрещает добавлять user_id к публичному query."""

    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, ge=0, le=2147483647)


class ReadBody(BaseModel):
    """Пустое действие, не принимающее другую личность из JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")


async def call(request, method, *args):
    """Известный отказ не раскрывает служебный токен или сырой ответ сервиса."""
    client = request.app.state.notifications_client
    if client is None:
        raise HTTPException(503, "Notifications unavailable")
    try:
        return await getattr(client, method)(*args)
    except NotificationRequestError as exc:
        raise HTTPException(
            exc.status,
            "Notification request failed",
            headers={"Cache-Control": "private, no-store"},
        ) from exc


@router.get("", response_model=list[Notification])
async def list_notifications(
    request: Request,
    response: Response,
    user: User,
    query: Annotated[PageQuery, Query()],
):
    """Не даёт администратору скрытого доступа к чужой личной переписке."""
    response.headers["Cache-Control"] = "private, no-store"
    return await call(request, "list_for", user.id, query.offset)


@router.get("/count", response_model=NotificationCount)
async def count(request: Request, response: Response, user: User):
    """Показывает личный счётчик непрочитанного."""
    response.headers["Cache-Control"] = "private, no-store"
    return NotificationCount(unread=await call(request, "count", user.id))


@router.post("/{notification_id}/read")
async def read(
    notification_id: Annotated[int, Path(ge=1, le=2147483647)],
    request: Request,
    response: Response,
    user: User,
    body: ReadBody | None = None,
):
    """Служебный UUID для UPDATE берёт из JWT; 200JSON удобен общему клиенту портала."""
    response.headers["Cache-Control"] = "private, no-store"
    await call(request, "mark_read", notification_id, user.id)
    return {"read": True}
