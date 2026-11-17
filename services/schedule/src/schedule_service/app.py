from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from schedule_service.api.router import router
from schedule_service.application.ports.schedule_cache import ScheduleCache
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.config import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Закрывает ресурсы приложения при завершении HTTP-процесса.

    Args:
        app: Приложение с ресурсами и зависимостями в app.state.
    """
    try:
        yield
    finally:
        await app.state.schedule_cache.aclose()
        await app.state.engine.dispose()


def create_app(
    settings: Settings,
    engine: AsyncEngine,
    uow_factory: UnitOfWorkFactory,
    schedule_cache: ScheduleCache,
) -> FastAPI:
    """Собирает HTTP-приложение с переданными зависимостями.

    Args:
        settings: Настройки текущего сервиса.
        engine: Объект SQLAlchemy для соединений с базой.
        uow_factory: Фабрика отдельной транзакции с её репозиториями.
        schedule_cache: Кеш расписания с блокировкой заполнения и поколением.

    Returns:
        Приложение FastAPI с маршрутами и зависимостями в app.state.
    """
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(router)
    app.state.settings = settings
    app.state.engine = engine
    app.state.uow_factory = uow_factory
    app.state.schedule_cache = schedule_cache
    return app
