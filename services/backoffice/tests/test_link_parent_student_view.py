"""Проверки привязки через настоящую страницу, HTTP-адаптер и журнал Django."""

import httpx
import pytest
from django.urls import reverse

from backoffice_admin import views
from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db

IDS = {
    "parent_id": "eeaa1d14-ebc2-41f5-8249-1a564a5e06df",
    "student_id": "7cf0a05a-6c80-4c20-b646-e7a360183e72",
}


@pytest.fixture
def link_page(client, django_user_model, monkeypatch):
    staff = django_user_model.objects.create_user(username="link-staff", is_staff=True)
    client.force_login(staff)
    original_client = httpx.Client
    requests = []

    def install(handler):
        def send(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            views.httpx,
            "Client",
            lambda **kwargs: original_client(
                **kwargs, transport=httpx.MockTransport(send)
            ),
        )

    return client, staff, install, requests


def test_get_shows_uuid_form_without_contacting_gateway(link_page):
    client, _, install, requests = link_page
    install(lambda request: httpx.Response(201))

    response = client.get(reverse("backoffice-link-parent-student"))

    assert response.status_code == 200
    assert b'name="parent_id"' in response.content
    assert b'name="student_id"' in response.content
    assert b"csrfmiddlewaretoken" in response.content
    assert requests == []
    assert not AdminActionRecord.objects.exists()


@pytest.mark.parametrize("field", ["parent_id", "student_id"])
def test_invalid_uuid_prevents_request_and_audit(link_page, field):
    client, _, install, requests = link_page
    install(lambda request: httpx.Response(201))

    response = client.post(
        reverse("backoffice-link-parent-student"), {**IDS, field: "bad"}
    )

    assert response.status_code == 200
    assert field in response.context["form"].errors
    assert requests == []
    assert not AdminActionRecord.objects.exists()


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (201, "created", "Связь родителя и ученика создана."),
        (204, "already_exists", "Связь родителя и ученика уже существует."),
    ],
)
def test_both_success_outcomes_redirect_and_audit(link_page, status, code, message):
    client, staff, install, requests = link_page
    install(lambda request: httpx.Response(status))

    response = client.post(reverse("backoffice-link-parent-student"), IDS)

    assert response.status_code == 302
    assert response.url == "/admin/link-parent-student/"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PUT"
    assert str(request.url) == (
        "http://gateway.test/internal/backoffice/parents/"
        f"{IDS['parent_id']}/children/{IDS['student_id']}"
    )
    assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id
    assert record.action == "link_parent_student"
    assert record.target_ids == IDS
    assert record.succeeded is True
    assert record.result_code == code
    page = client.get(response.url)
    assert message in page.content.decode()
    assert len(requests) == 1
    assert AdminActionRecord.objects.count() == 1


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (404, "gateway_http_404", "Родитель или ученик не найден."),
        (422, "gateway_http_422", "У пользователей должны быть роли"),
        (403, "gateway_http_403", "Gateway вернул ошибку."),
        (500, "gateway_http_500", "Gateway вернул ошибку."),
        (200, "gateway_protocol_error", "Gateway вернул некорректный ответ."),
    ],
)
def test_failure_keeps_form_and_records_attempted_ids(link_page, status, code, message):
    client, staff, install, requests = link_page
    install(lambda request: httpx.Response(status, text="private upstream details"))

    response = client.post(reverse("backoffice-link-parent-student"), IDS)

    assert response.status_code == 200
    form = response.context["form"]
    assert form.is_bound
    assert dict(form.data.items()) == IDS
    assert form.non_field_errors()
    assert message in response.content.decode()
    assert b"private upstream details" not in response.content
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id
    assert record.action == "link_parent_student"
    assert record.target_ids == IDS
    assert record.succeeded is False
    assert record.result_code == code
    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_error_does_not_retry_or_claim_no_link(link_page, error):
    client, _, install, requests = link_page

    def fail(request):
        raise error("private network details", request=request)

    install(fail)
    response = client.post(reverse("backoffice-link-parent-student"), IDS)

    assert response.status_code == 200
    assert "Проверьте наличие связи" in response.content.decode()
    assert b"private network details" not in response.content
    record = AdminActionRecord.objects.get()
    assert record.target_ids == IDS
    assert record.succeeded is False
    assert record.result_code == "gateway_result_unknown"
    assert len(requests) == 1
