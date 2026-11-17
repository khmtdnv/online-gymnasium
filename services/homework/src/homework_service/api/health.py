"""Проверки процесса и подключения к БД без вызова учебного сценария."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Подтверждает работу HTTP-процесса без обращения к базе."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    """Проверяет доступность БД, не раскрывая детали соединения.

    Args:
        request: Запрос с engine и функцией проверки в app.state.

    Returns:
        Успешный статус готовности инфраструктуры.

    Raises:
        HTTPException: База недоступна (503).
    """
    try:
        await request.app.state.database_probe(request.app.state.engine)
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok"}
