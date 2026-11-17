"""Новый Analytics API закрыт отдельным сервисным секретом и ограничивает запрос."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx


def test_internal_audit_requires_service_token_and_validates_period():
    from analytics_service.api.app import create_app

    repository = SimpleNamespace(
        list_events=AsyncMock(return_value=[]), get_progress=AsyncMock(return_value=[])
    )
    app = create_app(
        lambda: None,
        audit_repository_factory=lambda: repository,
        audit_service_token="test-read",
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            url = "/internal/audit?date_from=2026-10-01&date_to=2026-10-22"
            assert (await client.get(url)).status_code == 401
            headers = {"Authorization": "Bearer test-read"}
            response = await client.get(url, headers=headers)
            assert response.status_code == 200 and response.json() == []
            assert response.headers["cache-control"] == "private, no-store"
            assert (
                await client.get(url + "&limit=101", headers=headers)
            ).status_code == 422
            assert (
                await client.get(url + "&actor_id=spoof", headers=headers)
            ).status_code == 422
            assert (
                await client.get(
                    "/internal/audit?date_from=0001-01-01&date_to=0001-01-02",
                    headers=headers,
                )
            ).status_code == 422
            assert (
                await client.get(
                    "/internal/progress?class_id=7&date_from=2026-10-22&date_to=2026-10-01",
                    headers=headers,
                )
            ).status_code == 422
            repository.get_progress.side_effect = RuntimeError("CH unavailable")
            assert (
                await client.get(
                    "/internal/progress?class_id=7&date_from=2026-10-01&date_to=2026-10-22",
                    headers=headers,
                )
            ).status_code == 503

    asyncio.run(run())
