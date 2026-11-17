"""Браузер не выбирает адресата уведомлений и не подставляет его в прочтение."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI


def test_notifications_always_use_authenticated_user_and_reject_extra_identity():
    from gateway_service.api.notifications import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role

    user_id = uuid4()
    app = FastAPI()
    app.include_router(router)

    async def user():
        return GetCurrentUserResult(
            id=user_id, email="student@example.test", role=Role.STUDENT
        )

    app.dependency_overrides[get_authenticated_user] = user
    client = SimpleNamespace(
        list_for=AsyncMock(return_value=[]),
        count=AsyncMock(return_value=1),
        mark_read=AsyncMock(),
    )
    app.state.notifications_client = client

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            assert (
                await http.get(f"/api/v1/notifications?user_id={uuid4()}")
            ).status_code == 422
            assert (await http.get("/api/v1/notifications?offset=0")).json() == []
            client.list_for.assert_awaited_once_with(user_id, 0)
            assert (await http.get("/api/v1/notifications/count")).json() == {
                "unread": 1
            }
            assert (
                await http.post(
                    "/api/v1/notifications/1/read", json={"user_id": str(uuid4())}
                )
            ).status_code == 422
            assert (
                await http.post("/api/v1/notifications/1/read", json={})
            ).json() == {"read": True}
            client.mark_read.assert_awaited_once_with(1, user_id)

    asyncio.run(run())
