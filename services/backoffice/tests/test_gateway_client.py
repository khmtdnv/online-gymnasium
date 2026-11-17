import json
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from backoffice_admin.gateway_client import (
    GatewayBackofficeClient,
    GatewayProtocolError,
    GatewayUser,
    GatewayUserAlreadyExistsError,
)


def test_create_user_sends_private_request_and_returns_gateway_response() -> None:
    expected = {
        "id": "dd253ef5-e13e-4f67-a0da-ff63265a4b8c",
        "email": "student@example.test",
        "role": "student",
        "is_active": True,
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://gateway.test/internal/backoffice/users"
        assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
        assert json.loads(request.content) == {
            "email": "student@example.test",
            "password": "test-password",
            "role": "student",
            "first_name": "Тестовый",
            "last_name": "Пользователь",
        }
        return httpx.Response(201, json=expected)

    with httpx.Client(
        base_url="http://gateway.test",
        transport=httpx.MockTransport(handle_request),
    ) as http_client:
        gateway = GatewayBackofficeClient(http_client, "test-service-token")
        result = gateway.create_user(
            email="student@example.test",
            password="test-password",
            role="student",
            first_name="Тестовый",
            last_name="Пользователь",
        )

    assert isinstance(result, GatewayUser)
    assert result.id == UUID("dd253ef5-e13e-4f67-a0da-ff63265a4b8c")
    assert result.model_dump(mode="json", exclude_defaults=True) == expected


def test_create_user_translates_duplicate_email_conflict() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(409, json={"detail": "Email already exists"})
    )

    with httpx.Client(base_url="http://gateway.test", transport=transport) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(GatewayUserAlreadyExistsError) as error:
            gateway.create_user(
                "student@example.test",
                "test-password",
                "student",
                first_name="Тестовый",
                last_name="Пользователь",
            )

    assert isinstance(error.value.__cause__, httpx.HTTPStatusError)


@pytest.mark.parametrize("status_code", [403, 500])
def test_create_user_does_not_mislabel_other_http_errors(status_code: int) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json={"detail": "Request failed"})
    )

    with httpx.Client(base_url="http://gateway.test", transport=transport) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(httpx.HTTPStatusError) as error:
            gateway.create_user(
                "student@example.test",
                "test-password",
                "student",
                first_name="Тестовый",
                last_name="Пользователь",
            )

    assert error.value.response.status_code == status_code


@pytest.mark.parametrize("missing_field", ["id", "email", "role", "is_active"])
def test_create_user_rejects_missing_response_fields(missing_field: str) -> None:
    payload = {
        "id": "dd253ef5-e13e-4f67-a0da-ff63265a4b8c",
        "email": "student@example.test",
        "role": "student",
        "is_active": True,
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }
    del payload[missing_field]
    transport = httpx.MockTransport(lambda request: httpx.Response(201, json=payload))
    with httpx.Client(base_url="http://gateway.test", transport=transport) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(GatewayProtocolError) as error:
            gateway.create_user(
                "student@example.test",
                "test-password",
                "student",
                first_name="Тестовый",
                last_name="Пользователь",
            )
    assert isinstance(error.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", "not-a-uuid"), ("role", "owner"), ("is_active", "false"), ("is_active", 0)],
)
def test_create_user_rejects_invalid_response_values(field: str, value: object) -> None:
    payload = {
        "id": "dd253ef5-e13e-4f67-a0da-ff63265a4b8c",
        "email": "student@example.test",
        "role": "student",
        "is_active": True,
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }
    payload[field] = value
    transport = httpx.MockTransport(lambda request: httpx.Response(201, json=payload))
    with httpx.Client(base_url="http://gateway.test", transport=transport) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(GatewayProtocolError):
            gateway.create_user(
                "student@example.test",
                "test-password",
                "student",
                first_name="Тестовый",
                last_name="Пользователь",
            )


@pytest.mark.parametrize("content", [b"not-json", b"[]", b"null"])
def test_create_user_rejects_invalid_response_body(content: bytes) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(201, content=content)
    )
    with httpx.Client(base_url="http://gateway.test", transport=transport) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(GatewayProtocolError):
            gateway.create_user(
                "student@example.test",
                "test-password",
                "student",
                first_name="Тестовый",
                last_name="Пользователь",
            )


@pytest.mark.parametrize("empty", [False, True])
def test_list_users_sends_private_request_and_returns_typed_users(empty: bool) -> None:
    payload = (
        []
        if empty
        else [
            {
                "id": "dd253ef5-e13e-4f67-a0da-ff63265a4b8c",
                "email": "student@example.test",
                "role": "student",
                "is_active": False,
                "first_name": "Тестовый",
                "last_name": "Пользователь",
            }
        ]
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "http://gateway.test/internal/backoffice/users"
        assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
        return httpx.Response(200, json=payload)

    with httpx.Client(
        base_url="http://gateway.test", transport=httpx.MockTransport(handle_request)
    ) as client:
        users = GatewayBackofficeClient(client, "test-service-token").list_users()
    assert len(users) == (0 if empty else 1)
    if not empty:
        assert isinstance(users[0], GatewayUser)
        assert users[0].id == UUID("dd253ef5-e13e-4f67-a0da-ff63265a4b8c")
        assert users[0].is_active is False


@pytest.mark.parametrize("content", [b"not-json", b"{}", b"[{}]", b"null"])
def test_list_users_rejects_invalid_response_body(content: bytes) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=content)
    )
    with (
        httpx.Client(base_url="http://gateway.test", transport=transport) as client,
        pytest.raises(GatewayProtocolError),
    ):
        GatewayBackofficeClient(client, "test-service-token").list_users()


@pytest.mark.parametrize(("status_code", "created"), [(201, True), (204, False)])
def test_link_parent_student_sends_private_request_and_handles_empty_body(
    status_code: int,
    created: bool,
) -> None:
    parent_id = UUID("dd253ef5-e13e-4f67-a0da-ff63265a4b8c")
    student_id = UUID("184b9c73-76f5-4090-b504-19f1d693b01c")

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert str(request.url) == (
            "http://gateway.test/internal/backoffice/parents/"
            "dd253ef5-e13e-4f67-a0da-ff63265a4b8c/children/"
            "184b9c73-76f5-4090-b504-19f1d693b01c"
        )
        assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
        return httpx.Response(status_code)

    with httpx.Client(
        base_url="http://gateway.test", transport=httpx.MockTransport(handle_request)
    ) as client:
        result = GatewayBackofficeClient(
            client, "test-service-token"
        ).link_parent_student(parent_id, student_id)
    assert result is created


@pytest.mark.parametrize("status_code", [200, 202])
def test_link_parent_student_rejects_unexpected_success_status(
    status_code: int,
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    with (
        httpx.Client(base_url="http://gateway.test", transport=transport) as client,
        pytest.raises(GatewayProtocolError),
    ):
        GatewayBackofficeClient(client, "test-service-token").link_parent_student(
            UUID(int=1), UUID(int=2)
        )


@pytest.mark.parametrize("operation", ["list", "link"])
@pytest.mark.parametrize("status_code", [403, 404, 422, 500])
def test_remote_http_errors_are_not_hidden(operation: str, status_code: int) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code))
    with httpx.Client(base_url="http://gateway.test", transport=transport) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(httpx.HTTPStatusError) as error:
            if operation == "list":
                gateway.list_users()
            else:
                gateway.link_parent_student(UUID(int=1), UUID(int=2))
    assert error.value.response.status_code == status_code


@pytest.mark.parametrize("operation", ["create", "list", "link"])
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_errors_are_not_mislabeled(
    operation: str,
    error_type: type[httpx.TransportError],
) -> None:
    def handle_request(request: httpx.Request) -> httpx.Response:
        raise error_type("Gateway unavailable", request=request)

    with httpx.Client(
        base_url="http://gateway.test", transport=httpx.MockTransport(handle_request)
    ) as client:
        gateway = GatewayBackofficeClient(client, "test-service-token")
        with pytest.raises(error_type):
            if operation == "create":
                gateway.create_user(
                    "student@example.test",
                    "test-password",
                    "student",
                    first_name="Тестовый",
                    last_name="Пользователь",
                )
            elif operation == "list":
                gateway.list_users()
            else:
                gateway.link_parent_student(UUID(int=1), UUID(int=2))
