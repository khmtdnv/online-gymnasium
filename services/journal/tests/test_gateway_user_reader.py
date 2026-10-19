"""Контракт HTTP-чтения пользователей из Gateway."""

import asyncio
from uuid import UUID

import httpx
import pytest

USER_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
OTHER_ID = UUID("bbbbbbbb-0000-4000-8000-000000000002")
VALID = {"id": str(USER_ID), "role": "student", "is_active": True}


def perform_lookup(handler, *, follow_redirects=False):
    """Запускает настоящий адаптер над управляемым HTTP-транспортом."""
    from journal_service.infrastructure.gateway_user_reader import HttpGatewayUserReader

    async def run():
        async with httpx.AsyncClient(
            base_url="http://gateway.test",
            transport=httpx.MockTransport(handler),
            follow_redirects=follow_redirects,
        ) as client:
            reader = HttpGatewayUserReader(client, "journal-only-test-token")
            return await reader.get_user(USER_ID)

    return asyncio.run(run())


def test_get_user_sends_one_authenticated_get() -> None:
    """Ловит неверный URL, отсутствие секрета, повторный запрос и timeout."""
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=VALID)

    result = perform_lookup(respond)
    assert result.id == USER_ID
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"http://gateway.test/internal/users/{USER_ID}"
    assert request.headers["authorization"] == "Bearer journal-only-test-token"
    assert set(request.extensions["timeout"].values()) == {5.0}


def test_get_user_returns_validated_info() -> None:
    from journal_service.application.ports.gateway_user_reader import GatewayUserInfo

    result = perform_lookup(lambda request: httpx.Response(200, json=VALID))
    assert isinstance(result, GatewayUserInfo)
    assert result.model_dump() == {"id": USER_ID, "role": "student", "is_active": True}


@pytest.mark.parametrize("role", ["student", "teacher", "parent", "admin"])
def test_get_user_preserves_role_and_inactive_state(role) -> None:
    payload = {**VALID, "role": role, "is_active": False}
    result = perform_lookup(lambda request: httpx.Response(200, json=payload))
    assert result.role == role
    assert result.is_active is False


@pytest.mark.parametrize("body", [b'{"error":{"code":"not_found"}}', b"not JSON"])
def test_404_returns_none(body) -> None:
    result = perform_lookup(lambda request: httpx.Response(404, content=body))
    assert result is None


@pytest.mark.parametrize("status", [301, 302, 401, 403, 422, 500, 503])
def test_non_success_is_unavailable(status) -> None:
    from journal_service.application.ports.errors import UserLookupUnavailableError

    with pytest.raises(UserLookupUnavailableError):
        perform_lookup(
            lambda request: httpx.Response(status, content=b"private-details")
        )


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_failure_is_unavailable(error) -> None:
    from journal_service.application.ports.errors import UserLookupUnavailableError

    def fail(request):
        raise error("private-network-details", request=request)

    with pytest.raises(UserLookupUnavailableError):
        perform_lookup(fail)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"role": "student", "is_active": True},
        {"id": str(USER_ID), "is_active": True},
        {"id": str(USER_ID), "role": "student"},
        {**VALID, "role": "unknown"},
        {**VALID, "id": "invalid-uuid"},
        {**VALID, "is_active": "true"},
        {**VALID, "is_active": 1},
        {**VALID, "is_active": 0},
        {**VALID, "is_active": None},
        [],
    ],
)
def test_invalid_payload_is_unavailable(payload) -> None:
    from journal_service.application.ports.errors import UserLookupUnavailableError

    with pytest.raises(UserLookupUnavailableError):
        perform_lookup(lambda request: httpx.Response(200, json=payload))


def test_invalid_json_is_unavailable() -> None:
    from journal_service.application.ports.errors import UserLookupUnavailableError

    with pytest.raises(UserLookupUnavailableError):
        perform_lookup(lambda request: httpx.Response(200, content=b"{broken"))


def test_wrong_user_id_is_unavailable() -> None:
    from journal_service.application.ports.errors import UserLookupUnavailableError

    with pytest.raises(UserLookupUnavailableError):
        perform_lookup(
            lambda request: httpx.Response(200, json={**VALID, "id": str(OTHER_ID)})
        )


def test_redirect_is_not_followed_even_if_client_allows_it() -> None:
    from journal_service.application.ports.errors import UserLookupUnavailableError

    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://another.test/users"})

    with pytest.raises(UserLookupUnavailableError):
        perform_lookup(redirect, follow_redirects=True)
    assert len(requests) == 1
    assert requests[0].url.host == "gateway.test"


def test_reader_does_not_close_injected_client() -> None:
    from journal_service.infrastructure.gateway_user_reader import HttpGatewayUserReader

    async def run():
        async with httpx.AsyncClient(
            base_url="http://gateway.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=VALID)
            ),
        ) as client:
            reader = HttpGatewayUserReader(client, "journal-only-test-token")
            await reader.get_user(USER_ID)
            assert not client.is_closed
            assert (await client.get("/health/live")).status_code == 200

    asyncio.run(run())
