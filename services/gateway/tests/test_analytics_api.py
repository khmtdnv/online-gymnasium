"""Публичная аналитика только для администратора; ошибки владельца не скрываются."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
from fastapi import FastAPI


def test_admin_report_rejects_other_roles_and_batches_names():
    from gateway_service.api.analytics import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role
    from gateway_service.infrastructure.analytics_client import (
        AnalyticsUnavailableError,
    )

    role = Role.STUDENT
    app = FastAPI()
    app.include_router(router)

    async def user():
        return GetCurrentUserResult(
            id=UUID(int=1), email="admin@example.test", role=role
        )

    app.dependency_overrides[get_authenticated_user] = user
    app.state.analytics_client = SimpleNamespace(
        get_progress=AsyncMock(
            return_value=[
                {
                    "student_id": str(UUID(int=2)),
                    "subject_id": 3,
                    "graded_count": 1,
                    "average_grade": 4.0,
                }
            ]
        )
    )
    app.state.schedule_client = SimpleNamespace(
        get_subject_names=AsyncMock(return_value={3: "Математика"})
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                get_by_ids=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id=UUID(int=2),
                            first_name="Иван",
                            last_name="Петров",
                            middle_name="",
                        ),
                    ]
                )
            )
        )

    app.state.uow_factory = uow

    async def run():
        nonlocal role
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            url = "/api/v1/analytics/progress?class_id=7&date_from=2026-10-01&date_to=2026-10-22"
            assert (await client.get(url)).status_code == 403
            app.state.analytics_client.get_progress.assert_not_awaited()
            role = Role.ADMIN
            response = await client.get(url)
            assert response.status_code == 200
            assert response.json()[0]["student_name"] == "Петров Иван"
            assert response.json()[0]["subject_name"] == "Математика"
            assert response.headers["cache-control"] == "private, no-store"
            assert (await client.get(url + "&student_id=spoof")).status_code == 422
            app.state.analytics_client.get_progress.side_effect = (
                AnalyticsUnavailableError()
            )
            assert (await client.get(url)).status_code == 503

    asyncio.run(run())
