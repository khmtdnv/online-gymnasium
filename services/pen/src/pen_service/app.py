"""Закрытый HTTP API хранилища; пользовательские права проверяет Gateway."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from pen_service.contracts import SavedBatch, StrokeBatch
from pen_service.storage import PenConflictError, PenPageFullError, PenStore


def create_app(store: PenStore, service_token: str, *, lifespan=None) -> FastAPI:
    """Внедряет отдельное хранилище и credential без открытия сессии.

    Args:
        store: Хранилище со своей фабрикой коротких сессий.
        service_token: Единственный доверенный Gateway→Pen секрет.
        lifespan: Освобождение ресурсов запускающего процесса.

    Returns:
        Закрытое приложение, без публичной пользовательской авторизации.
    """
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    bearer = HTTPBearer(auto_error=False)

    def require_gateway(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
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

    route = "/internal/lessons/{lesson_id}/students/{student_id}/batches"
    LessonId = Annotated[int, Path(ge=1, le=2147483647)]

    @app.get(
        route, response_model=list[SavedBatch], dependencies=[Depends(require_gateway)]
    )
    async def history(
        lesson_id: LessonId,
        student_id: UUID,
        after: Annotated[int, Query(ge=0, le=4096)] = 0,
    ):
        """Читает одну страницу истории; пустая следующая страница означает конец."""
        try:
            return await store.history(lesson_id, student_id, after=after)
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Pen storage unavailable") from exc

    @app.post(route, response_model=SavedBatch, dependencies=[Depends(require_gateway)])
    async def append(lesson_id: LessonId, student_id: UUID, body: StrokeBatch):
        """Ответ подтверждает commit; клиент не различает новый и повторный ACK."""
        try:
            return await store.append(lesson_id, student_id, body)
        except PenConflictError as exc:
            raise HTTPException(409, "Pen batch conflict") from exc
        except PenPageFullError as exc:
            raise HTTPException(413, "Pen page full") from exc
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Pen storage unavailable") from exc

    @app.get("/health/live")
    async def live():
        """Подтверждает работоспособность HTTP-процесса, не его зависимости."""
        return {"status": "ok"}

    return app
