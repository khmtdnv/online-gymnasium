"""Сборка HTTP-процесса с закрытием собственного connection pool."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pen_service.app import create_app
from pen_service.config import PenSettings
from pen_service.storage import PenStore

settings = PenSettings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)


@asynccontextmanager
async def lifespan(app):
    """Освобождает подключения при завершении процесса Uvicorn."""
    try:
        yield
    finally:
        await engine.dispose()


app = create_app(
    PenStore(async_sessionmaker(engine, expire_on_commit=False)),
    settings.gateway_service_token,
    lifespan=lifespan,
)
