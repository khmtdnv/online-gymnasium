import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_service.app import create_app
from gateway_service.application.errors import AuthenticationError
from gateway_service.application.ports.token_service import DecodedRefresh
from gateway_service.config import GatewaySettings


@pytest.mark.parametrize(
    "scenario",
    ["active", "consumed", "missing", "empty", "invalid", "database_failure"],
)
@pytest.mark.parametrize("secure", [False, True])
def test_logout_revokes_cookie_token_without_hiding_database_failure(
    scenario: str,
    secure: bool,
) -> None:
    decoded = DecodedRefresh(user_id=uuid4(), jti=uuid4())
    users = SimpleNamespace(
        consume_refresh_token=AsyncMock(return_value=scenario != "consumed")
    )
    uow = AsyncMock()
    uow.__aenter__.return_value = SimpleNamespace(users=users)
    uow_factory = Mock(return_value=uow)
    token_service = Mock()
    token_service.decode_refresh.return_value = decoded
    if scenario == "invalid":
        token_service.decode_refresh.side_effect = AuthenticationError
    if scenario == "database_failure":
        users.consume_refresh_token.side_effect = RuntimeError("database unavailable")
    settings = GatewaySettings(
        database_url="postgresql+asyncpg://gateway:password@localhost/gateway",
        jwt_secret="test-signing-secret-for-hs256-32-bytes",
        backoffice_service_token="test-backoffice-token",
        refresh_cookie_secure=secure,
        _env_file=None,
    )
    app = create_app(settings, AsyncMock(), uow_factory, Mock(), token_service)

    async def request_logout():
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="https://testserver" if secure else "http://testserver",
        ) as client:
            if scenario != "missing":
                client.cookies.set(
                    "refresh_token",
                    "" if scenario == "empty" else "old-refresh-token",
                    domain="testserver.local",
                    path="/api/v1/auth",
                )
            response = await client.post(
                "/api/v1/auth/logout", headers={"Origin": "http://localhost:8080"}
            )
            return response, client.cookies.get("refresh_token")

    response, remaining_cookie = asyncio.run(request_logout())

    if scenario in {"missing", "empty"}:
        token_service.decode_refresh.assert_not_called()
        uow_factory.assert_not_called()
        users.consume_refresh_token.assert_not_awaited()
    elif scenario == "invalid":
        token_service.decode_refresh.assert_called_once_with("old-refresh-token")
        uow_factory.assert_not_called()
        users.consume_refresh_token.assert_not_awaited()
    else:
        token_service.decode_refresh.assert_called_once_with("old-refresh-token")
        users.consume_refresh_token.assert_awaited_once_with(
            decoded.jti, decoded.user_id
        )

    if scenario == "database_failure":
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "database unavailable" not in response.text
        assert "set-cookie" not in response.headers
        assert remaining_cookie == "old-refresh-token"
        assert uow.__aexit__.await_args.args[0] is RuntimeError
    else:
        assert response.status_code == 204
        assert response.content == b""
        cookie_header = response.headers["set-cookie"].lower()
        assert "refresh_token=" in cookie_header
        assert "max-age=0" in cookie_header
        assert "path=/api/v1/auth" in cookie_header
        attributes = {part.strip() for part in cookie_header.split(";")}
        assert ("secure" in attributes) is secure
        assert remaining_cookie is None
        if scenario in {"active", "consumed"}:
            uow.__aexit__.assert_awaited_once_with(None, None, None)

    token_service.issue_access.assert_not_called()
    token_service.issue_refresh.assert_not_called()
