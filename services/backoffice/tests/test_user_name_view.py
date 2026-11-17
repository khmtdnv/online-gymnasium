"""Проверяет редактирование ФИО и локальный журнал через настоящий HTTP-клиент."""

import json
from uuid import uuid4

import httpx
import pytest
from django.test import Client

from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile_page(client, django_user_model, monkeypatch):
    staff = django_user_model.objects.create_user(
        username="profile-editor", is_staff=True
    )
    client.force_login(staff)
    user_id = uuid4()
    original = httpx.Client
    profile = {
        "id": str(user_id),
        "email": "old@example.com",
        "role": "student",
        "is_active": True,
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }
    calls = []

    def install(status=200):
        def reply(request):
            calls.append(request)
            assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
            if request.method == "GET":
                return httpx.Response(200, json=profile)
            assert request.method == "PUT"
            assert request.url.path == f"/internal/backoffice/users/{user_id}/name"
            return httpx.Response(
                status, json={**profile, **json.loads(request.content)}
            )

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(reply)),
        )

    install()
    return client, staff, f"/admin/users/{user_id}/name/", calls, install


def test_edit_user_loads_saved_names(profile_page):
    client, _, url, _, _ = profile_page
    response = client.get(url)
    assert response.status_code == 200
    assert "old@example.com" in response.content.decode()
    assert not response.context["form"].is_bound
    assert response.context["form"].initial["first_name"] == "Тестовый"


def test_edit_sends_only_names_and_audits_trusted_actor(profile_page):
    client, staff, url, calls, _ = profile_page
    response = client.post(
        url,
        {
            "first_name": " Иван ",
            "last_name": " Петров ",
            "middle_name": "",
            "role": "admin",
            "actor_id": "999",
        },
    )
    assert response.status_code == 302 and response.url == url
    assert json.loads(calls[-1].content) == {
        "first_name": "Иван",
        "last_name": "Петров",
        "middle_name": "",
    }
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id and record.succeeded is True
    assert set(record.target_ids) == {"user_id"}


def test_invalid_name_does_not_send_update(profile_page):
    client, _, url, calls, _ = profile_page
    response = client.post(url, {"first_name": " ", "last_name": "Петров"})
    assert response.status_code == 200
    assert "first_name" in response.context["form"].errors
    assert [call.method for call in calls] == ["GET"]
    assert not AdminActionRecord.objects.exists()


def test_update_failure_preserves_form_and_records_unconfirmed_result(profile_page):
    client, _, url, _, install = profile_page
    install(503)
    response = client.post(url, {"first_name": "Иван", "last_name": "Петров"})
    assert response.status_code == 200
    assert response.context["form"].data["first_name"] == "Иван"
    assert "проверьте ФИО" in response.content.decode()
    record = AdminActionRecord.objects.get()
    assert (
        record.succeeded is False and record.result_code == "gateway_result_unconfirmed"
    )


def test_profile_post_requires_csrf(profile_page):
    _, staff, url, _, _ = profile_page
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    assert (
        client.post(url, {"first_name": "Иван", "last_name": "Петров"}).status_code
        == 403
    )
