"""Закрытый API требует свою служебную пару и не подтверждает чужое прочтение."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx


def test_private_notification_api_requires_service_and_preserves_read_ownership():
    from notifications_service.app import create_app

    user = uuid4()
    store = SimpleNamespace(
        list_for=AsyncMock(return_value=[]),
        unread_count=AsyncMock(return_value=1),
        mark_read=AsyncMock(side_effect=lambda id_, user_id: user_id == user),
    )
    app = create_app(store, "test-service-only")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/internal/notifications?user_id={user}"
            assert (await client.get(path)).status_code == 401
            headers = {"Authorization": "Bearer test-service-only"}
            response = await client.get(path, headers=headers)
            assert response.status_code == 200 and response.json() == []
            assert response.headers["cache-control"] == "private, no-store"
            assert (
                await client.get(
                    f"/internal/notifications/count?user_id={user}", headers=headers
                )
            ).json() == {"unread": 1}
            read = "/internal/notifications/1/read"
            assert (
                await client.post(read, headers=headers, json={"user_id": str(uuid4())})
            ).status_code == 404
            assert (
                await client.post(read, headers=headers, json={"user_id": str(user)})
            ).status_code == 204

    asyncio.run(run())
