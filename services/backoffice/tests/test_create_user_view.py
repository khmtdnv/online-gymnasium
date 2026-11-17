"""Проверки страницы через настоящий Django и HTTP-адаптер Gateway."""

import json

import httpx
import pytest
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse

from backoffice_admin import views
from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db

FORM_DATA = {
    "email": "student@example.test",
    "password": "private-test-password",
    "role": "student",
    "first_name": "Тестовый",
    "last_name": "Пользователь",
}
USER_RESPONSE = {
    "id": "dd253ef5-e13e-4f67-a0da-ff63265a4b8c",
    "email": "student@example.test",
    "role": "student",
    "is_active": True,
    "first_name": "Тестовый",
    "last_name": "Пользователь",
}


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(username="staff", is_staff=True)


@pytest.fixture
def staff_client(client, staff):
    client.force_login(staff)
    return client


@pytest.fixture
def gateway_transport(monkeypatch):
    """Подменяет только сеть, сохраняя настоящий клиент и разбор ответа."""
    original_client = httpx.Client
    requests = []

    def install(handler):
        def record_request(request):
            requests.append(request)
            return handler(request)

        def client_factory(**kwargs):
            return original_client(
                **kwargs, transport=httpx.MockTransport(record_request)
            )

        monkeypatch.setattr(views.httpx, "Client", client_factory)
        return requests

    return install


def test_create_sends_names_to_gateway(staff_client, gateway_transport):
    """Не теряет ФИО между полями Django и JSON Gateway."""
    names = {"first_name": "Иван", "last_name": "Петров", "middle_name": "Сергеевич"}
    requests = gateway_transport(
        lambda request: httpx.Response(201, json={**USER_RESPONSE, **names})
    )
    response = staff_client.post(
        reverse("backoffice-create-user"), {**FORM_DATA, **names}
    )
    assert response.status_code == 302
    assert json.loads(requests[0].content) == {**FORM_DATA, **names}
    assert AdminActionRecord.objects.get().succeeded is True


@pytest.mark.parametrize("authenticated", [False, True])
def test_nonstaff_cannot_send_create_command(
    client, django_user_model, gateway_transport, authenticated
):
    requests = gateway_transport(
        lambda request: httpx.Response(201, json=USER_RESPONSE)
    )
    if authenticated:
        client.force_login(django_user_model.objects.create_user(username="ordinary"))

    response = client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert response.status_code == 302
    assert response.url.startswith("/admin/login/?next=")
    assert requests == []
    assert not AdminActionRecord.objects.exists()


def test_get_renders_form_without_gateway_call(staff_client, gateway_transport):
    requests = gateway_transport(
        lambda request: httpx.Response(201, json=USER_RESPONSE)
    )
    response = staff_client.get(reverse("backoffice-create-user"))

    assert response.status_code == 200
    assert not response.context["form"].is_bound
    assert b"csrfmiddlewaretoken" in response.content
    assert b'name="password"' in response.content
    assert requests == []
    assert not AdminActionRecord.objects.exists()


@pytest.mark.parametrize(
    ("field", "value"), [("email", "invalid"), ("password", ""), ("role", "owner")]
)
def test_invalid_form_never_reaches_gateway(
    staff_client, gateway_transport, field, value
):
    requests = gateway_transport(
        lambda request: httpx.Response(201, json=USER_RESPONSE)
    )
    response = staff_client.post(
        reverse("backoffice-create-user"), {**FORM_DATA, field: value}
    )

    assert response.status_code == 200
    assert field in response.context["form"].errors
    assert requests == []
    assert not AdminActionRecord.objects.exists()


def test_success_redirects_and_records_only_safe_data(
    staff_client, staff, gateway_transport
):
    requests = gateway_transport(
        lambda request: httpx.Response(201, json=USER_RESPONSE)
    )
    response = staff_client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert response.status_code == 302
    assert response.url == "/admin/create-user/"
    assert len(requests) == 1
    assert str(requests[0].url) == "http://gateway.test/internal/backoffice/users"
    assert requests[0].headers["X-Backoffice-Service-Token"] == "test-service-token"
    assert json.loads(requests[0].content) == FORM_DATA
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id
    assert record.action == "create_user"
    assert record.succeeded is True
    assert record.target_ids == {"user_id": USER_RESPONSE["id"]}
    assert record.result_code == "created"
    saved_fields = str(AdminActionRecord.objects.values().get())
    assert FORM_DATA["password"] not in saved_fields
    assert "test-service-token" not in saved_fields

    page = staff_client.get(response.url)
    assert "Пользователь student@example.test создан." in page.content.decode()
    assert len(requests) == 1
    assert AdminActionRecord.objects.count() == 1


@pytest.mark.parametrize(
    ("status_code", "result_code", "error_field"),
    [
        (409, "email_already_exists", "email"),
        (403, "gateway_http_403", "__all__"),
        (422, "gateway_http_422", "__all__"),
        (500, "gateway_http_500", "__all__"),
    ],
)
def test_gateway_rejection_is_visible_and_audited(
    staff_client, staff, gateway_transport, status_code, result_code, error_field
):
    requests = gateway_transport(
        lambda request: httpx.Response(status_code, json={"detail": "internal details"})
    )
    response = staff_client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert response.status_code == 200
    assert error_field in response.context["form"].errors
    assert b"internal details" not in response.content
    assert len(requests) == 1
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id
    assert record.succeeded is False
    assert record.target_ids == {}
    assert record.result_code == result_code


@pytest.mark.parametrize("body", [b"not-json", b'{"id": "invalid"}'])
def test_invalid_gateway_response_does_not_claim_success(
    staff_client, gateway_transport, body
):
    requests = gateway_transport(lambda request: httpx.Response(201, content=body))
    response = staff_client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert response.status_code == 200
    assert response.context["form"].non_field_errors()
    record = AdminActionRecord.objects.get()
    assert record.succeeded is False
    assert record.result_code == "gateway_protocol_error"
    assert record.target_ids == {}
    assert len(requests) == 1


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_failure_records_unknown_result_without_automatic_retry(
    staff_client, gateway_transport, error_type
):
    def fail(request):
        raise error_type("private connection details", request=request)

    requests = gateway_transport(fail)
    response = staff_client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert response.status_code == 200
    assert "проверьте, создан ли пользователь" in response.content.decode()
    assert b"private connection details" not in response.content
    record = AdminActionRecord.objects.get()
    assert record.succeeded is False
    assert record.result_code == "gateway_result_unknown"
    assert len(requests) == 1


def test_missing_csrf_token_blocks_gateway_command(staff, gateway_transport):
    requests = gateway_transport(
        lambda request: httpx.Response(201, json=USER_RESPONSE)
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)

    response = client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert response.status_code == 403
    assert requests == []
    assert not AdminActionRecord.objects.exists()


def test_audit_failure_is_not_mislabeled_as_gateway_failure(
    staff_client, gateway_transport, monkeypatch
):
    requests = gateway_transport(
        lambda request: httpx.Response(201, json=USER_RESPONSE)
    )

    def fail_audit(**kwargs):
        raise DatabaseError("audit unavailable")

    monkeypatch.setattr(AdminActionRecord.objects, "create", fail_audit)
    with pytest.raises(DatabaseError, match="audit unavailable"):
        staff_client.post(reverse("backoffice-create-user"), FORM_DATA)

    assert len(requests) == 1
    assert not AdminActionRecord.objects.exists()
