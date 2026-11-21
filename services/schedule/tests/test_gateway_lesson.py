"""Gateway читает урок у владельца своим секретом, без зависимости от Homework."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2 as httpx
from fastapi import FastAPI
from test_homework_reads import lesson


def test_gateway_reads_authoritative_lesson_with_its_own_credential():
    from schedule_service.api.calendar_lessons import router

    repo = SimpleNamespace(get=AsyncMock(return_value=lesson()))

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(lessons=repo)

    app = FastAPI()
    app.state.uow_factory = uow
    app.state.settings = SimpleNamespace(
        gateway_service_token="gateway-only", homework_service_token="homework-only"
    )
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/internal/gateway-lessons/11"
            assert (await client.get(path)).status_code == 401
            assert (
                await client.get(
                    path, headers={"Authorization": "Bearer homework-only"}
                )
            ).status_code == 401
            headers = {"Authorization": "Bearer gateway-only"}
            response = await client.get(path, headers=headers)
            assert response.status_code == 200 and response.json()["class_id"] == 7
            repo.get.return_value = None
            assert (await client.get(path, headers=headers)).status_code == 404

    asyncio.run(run())
