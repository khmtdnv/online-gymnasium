"""Приватный список уведомлений; UUID владельца задаёт Gateway."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from notifications_service.contracts import Notification
from notifications_service.storage import NotificationStore


class PageQuery(BaseModel):
    """Пользователь и ограниченное смещение без дополнительных фильтров."""

    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    offset: int = Field(default=0, ge=0, le=2147483647)


class ReadBody(BaseModel):
    """Получатель, проверяемый атомарным UPDATE в хранилище."""

    model_config = ConfigDict(extra="forbid")
    user_id: UUID


def create_app(
    store: NotificationStore, service_token: str, *, lifespan=None
) -> FastAPI:
    """Собирает закрытый API, не принимающий пользовательские JWT напрямую."""
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    bearer = HTTPBearer(auto_error=False)

    def require_gateway(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if (
            not service_token
            or credentials is None
            or not secrets.compare_digest(
                credentials.credentials.encode(), service_token.encode()
            )
        ):
            raise HTTPException(
                401,
                "Invalid service credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(request, exc):
        return JSONResponse(
            status_code=503,
            content={"code": "notifications_unavailable"},
            headers={"Cache-Control": "private, no-store"},
        )

    router = APIRouter(
        prefix="/internal/notifications", dependencies=[Depends(require_gateway)]
    )

    @router.get("", response_model=list[Notification])
    async def list_notifications(
        response: Response, query: Annotated[PageQuery, Query()]
    ):
        """Отдаёт ровно страницу личного списка, не общую таблицу пользователей."""
        response.headers["Cache-Control"] = "private, no-store"
        return await store.list_for(query.user_id, 50, query.offset)

    @router.get("/count")
    async def unread(response: Response, user_id: UUID):
        """Счётчик относится к тому же пользователю, что и список."""
        response.headers["Cache-Control"] = "private, no-store"
        return {"unread": await store.unread_count(user_id)}

    @router.post("/{notification_id}/read", status_code=204)
    async def read(
        notification_id: Annotated[int, Path(ge=1, le=2147483647)],
        body: ReadBody,
        response: Response,
    ):
        """Чужой ID не изменяет запись и не получает успешное подтверждение."""
        response.headers["Cache-Control"] = "private, no-store"
        if not await store.mark_read(notification_id, body.user_id):
            raise HTTPException(404, "Notification not found")

    app.include_router(router)

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    return app
