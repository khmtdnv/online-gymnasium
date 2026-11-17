import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from fastapi import FastAPI

from gateway_service.api.security import get_authenticated_user
from gateway_service.domain.user import Role


def test_backoffice_identity_requires_service_token_admin_and_session():
    from gateway_service.api.backoffice_identity import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(backoffice_service_token="service-secret")
    user = SimpleNamespace(id=uuid4(), role=Role.ADMIN, session_id=uuid4())
    app.dependency_overrides[get_authenticated_user] = lambda: user

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/internal/backoffice/identity"
            assert (await client.get(path)).status_code == 403
            headers = {"X-Backoffice-Service-Token": "service-secret"}
            response = await client.get(path, headers=headers)
            assert response.status_code == 200
            assert response.json() == {
                "user_id": str(user.id),
                "session_id": str(user.session_id),
            }
            assert response.headers["cache-control"] == "private, no-store"
            user.role = Role.STUDENT
            assert (await client.get(path, headers=headers)).status_code == 403
            user.role = Role.ADMIN
            user.session_id = None
            assert (await client.get(path, headers=headers)).status_code == 401

    asyncio.run(run())


def test_backoffice_session_check_denies_revoked_session_or_non_admin():
    from gateway_service.api.backoffice_identity import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(backoffice_service_token="service-secret")
    user_id, session_id = uuid4(), uuid4()
    user = SimpleNamespace(id=user_id, role=Role.ADMIN, is_active=True)
    uow = AsyncMock()
    uow.__aenter__.return_value = SimpleNamespace(
        users=SimpleNamespace(get_by_id=AsyncMock(return_value=user)),
        auth_sessions=SimpleNamespace(is_active=AsyncMock(return_value=True)),
    )
    app.state.uow_factory = lambda: uow

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-Backoffice-Service-Token": "service-secret"}
            body = {"user_id": str(user_id), "session_id": str(session_id)}
            path = "/internal/backoffice/session"
            assert (await client.post(path, json=body)).status_code == 403
            assert (
                await client.post(path, headers=headers, json=body)
            ).status_code == 204
            uow.__aenter__.return_value.auth_sessions.is_active.return_value = False
            assert (
                await client.post(path, headers=headers, json=body)
            ).status_code == 401
            uow.__aenter__.return_value.auth_sessions.is_active.return_value = True
            user.role = Role.STUDENT
            assert (
                await client.post(path, headers=headers, json=body)
            ).status_code == 401
            user.role = Role.ADMIN
            user.is_active = False
            assert (
                await client.post(path, headers=headers, json=body)
            ).status_code == 401

    asyncio.run(run())


def test_trusted_backoffice_can_revoke_shared_session():
    from gateway_service.api.backoffice_identity import router

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(backoffice_service_token="service-secret")
    user_id, session_id = uuid4(), uuid4()
    sessions = SimpleNamespace(revoke=AsyncMock())
    uow = AsyncMock()
    uow.__aenter__.return_value = SimpleNamespace(auth_sessions=sessions)
    app.state.uow_factory = lambda: uow

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = {"user_id": str(user_id), "session_id": str(session_id)}
            path = "/internal/backoffice/session/revoke"
            assert (await client.post(path, json=body)).status_code == 403
            assert (
                await client.post(
                    path,
                    json=body,
                    headers={"X-Backoffice-Service-Token": "service-secret"},
                )
            ).status_code == 204
        sessions.revoke.assert_awaited_once_with(session_id, user_id)

    asyncio.run(run())
