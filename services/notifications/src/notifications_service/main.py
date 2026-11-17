"""HTTP-процесс с отдельным пулом соединений Notifications."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from notifications_service.app import create_app
from notifications_service.config import NotificationSettings
from notifications_service.storage import NotificationStore

settings = NotificationSettings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)


@asynccontextmanager
async def lifespan(app):
    """Закрывает пул PostgreSQL при завершении HTTP-процесса."""
    try:
        yield
    finally:
        await engine.dispose()


app = create_app(
    NotificationStore(async_sessionmaker(engine, expire_on_commit=False)),
    settings.gateway_service_token,
    lifespan=lifespan,
)
