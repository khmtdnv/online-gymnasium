"""Закрытые маршруты не позволяют обойти credential и ограничения координат."""

import asyncio
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_contracts import batch_data


def test_internal_api_is_closed_and_validates_before_storage():
    from pen_service.app import create_app
    from pen_service.storage import PenStore

    # Соединение не открывается: неавторизованные/невалидные данные не идут вБД.
    engine = create_async_engine(
        "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"
    )
    app = create_app(PenStore(async_sessionmaker(engine)), "test-only")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/internal/lessons/1/students/{uuid4()}/batches"
            assert (await client.get(path)).status_code == 401
            assert (await client.post(path, json=batch_data())).status_code == 401
            headers = {"Authorization": "Bearer test-only"}
            assert (
                await client.get(path + "?after=-1", headers=headers)
            ).status_code == 422
            assert (
                await client.post(path, json=batch_data(points=[]), headers=headers)
            ).status_code == 422
            assert (
                await client.get(path.replace("/1/", "/0/"), headers=headers)
            ).status_code == 422
        await engine.dispose()

    asyncio.run(run())
