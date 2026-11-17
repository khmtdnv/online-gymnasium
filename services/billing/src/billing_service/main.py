"""HTTP процесс Billing с собственными SQL и HTTP pools."""

from contextlib import asynccontextmanager

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from billing_service.app import create_app
from billing_service.config import BillingSettings
from billing_service.runtime import create_service

settings = BillingSettings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
http_client = httpx.AsyncClient(follow_redirects=False)


@asynccontextmanager
async def lifespan(app):
    """Освобождает оба пула при остановке Uvicorn."""
    try:
        async with http_client:
            yield
    finally:
        await engine.dispose()


service = create_service(
    settings, http_client, async_sessionmaker(engine, expire_on_commit=False)
)
app = create_app(service, settings.gateway_service_token, lifespan=lifespan)
