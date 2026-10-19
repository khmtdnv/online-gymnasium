"""Открытые проверки жизни HTTP-процесса и готовности его базы данных."""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    """Подтверждает, что HTTP-процесс отвечает, не обращаясь к базе данных.

    Returns:
        Статус ok без проверки внешних зависимостей.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(request: Request) -> dict[str, str]:
    """Проверяет готовность базы через переданную асинхронную функцию.

    Args:
        request: Запрос с readiness_check в состоянии приложения.

    Returns:
        Статус ok после успешной проверки зависимости.

    Raises:
        HTTPException: Проверка не настроена, база недоступна или истекли
            три секунды ожидания; HTTP-статус 503.
    """
    check = request.app.state.readiness_check
    if check is None:
        raise HTTPException(status_code=503, detail="Readiness check is not configured")
    try:
        async with asyncio.timeout(3):
            await check()
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ok"}
