"""Финансовая история Backoffice доступна только служебному клиенту."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI


def test_internal_payment_history_requires_service_token():
    """Без секрета Backoffice история платежей не раскрывается."""
    from gateway_service.api.backoffice_billing import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(backoffice_service_token="service-secret")
    app.state.billing_client = SimpleNamespace(payments=AsyncMock(return_value=[]))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/internal/backoffice/billing/payments?offset=0"
            assert (await client.get(path)).status_code == 403
            assert (
                await client.get(path, headers={"X-Backoffice-Service-Token": "wrong"})
            ).status_code == 403
            response = await client.get(
                path, headers={"X-Backoffice-Service-Token": "service-secret"}
            )
            assert response.status_code == 200
            assert response.json() == []
            assert response.headers["cache-control"] == "private, no-store"

    asyncio.run(run())
