"""Gateway имеет только отдельные права чтения, не полномочия Backoffice."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock

import httpx
from fastapi import Depends, FastAPI

from journal_service.api.dependencies import ServicePrincipal, get_authenticated_service
from journal_service.api.security import RequireServicePermission
from journal_service.config import JournalSettings
from journal_service.domain.school_class import Class


def test_billing_has_separate_read_only_credential():
    app = FastAPI()
    app.state.settings = JournalSettings(
        database_url="postgresql+asyncpg://test",
        backoffice_service_token="staff",
        billing_read_service_token="billing",
        _env_file=None,
    )

    @app.get(
        "/classes", dependencies=[Depends(RequireServicePermission("classes:read"))]
    )
    def read():
        return {}

    @app.post(
        "/classes", dependencies=[Depends(RequireServicePermission("classes:write"))]
    )
    def write():
        return {}

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer billing"}
            assert (await client.get("/classes", headers=headers)).status_code == 200
            assert (await client.post("/classes", headers=headers)).status_code == 403
            app.state.settings = app.state.settings.model_copy(
                update={"billing_read_service_token": "staff"}
            )
            assert (await client.get("/classes", headers=headers)).status_code == 503

    asyncio.run(run())


def test_gateway_read_token_is_distinct_and_cannot_write():
    app = FastAPI()
    app.state.settings = JournalSettings(
        database_url="postgresql+asyncpg://test",
        backoffice_service_token="staff",
        homework_service_token="homework",
        gateway_read_service_token="gateway",
        _env_file=None,
    )
    from journal_service.api.classes import router

    app.include_router(router)
    repository = SimpleNamespace(
        get_classes_by_ids=AsyncMock(
            return_value=[
                Class(
                    id=7,
                    name="7А",
                    study_year=2026,
                    created_at=datetime(2026, 10, 21, tzinfo=UTC),
                )
            ]
        )
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(classes=repository)

    app.state.uow_factory = uow

    @app.get("/read")
    def read(service: Annotated[ServicePrincipal, Depends(get_authenticated_service)]):
        return {
            "name": service.service_name,
            "permissions": sorted(service.permissions),
        }

    @app.post(
        "/write", dependencies=[Depends(RequireServicePermission("classes:write"))]
    )
    def write():
        return {}

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer gateway"}
            response = await client.get("/read", headers=headers)
            assert response.status_code == 200
            assert response.json() == {
                "name": "gateway",
                "permissions": [
                    "classes:read",
                    "diary:read",
                    "lesson-entries:read",
                    "student-current-class:read",
                ],
            }
            assert (await client.post("/write", headers=headers)).status_code == 403
            batch = await client.post(
                "/internal/classes/lookup", json={"ids": [7]}, headers=headers
            )
            assert batch.status_code == 200
            assert batch.json()[0]["name"] == "7А"
            repository.get_classes_by_ids.assert_awaited_once_with([7])
            assert (await client.get("/read")).status_code == 401
            app.state.settings = app.state.settings.model_copy(
                update={"gateway_read_service_token": "staff"}
            )
            assert (await client.get("/read", headers=headers)).status_code == 503

    asyncio.run(run())
