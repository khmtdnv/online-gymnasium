"""Проверяет поиск как закрытый прокси без передачи служебного токена браузеру."""

from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "patch", [{"role": "teacher"}, {"is_active": False}, {"id": "not-a-uuid"}]
)
def test_search_rejects_gateway_contract_violation(
    client, django_user_model, monkeypatch, patch
):
    """Не показывает некорректный профиль как допустимого ученика."""
    staff = django_user_model.objects.create_user(
        username="contract-check", is_staff=True
    )
    client.force_login(staff)
    original = httpx.Client
    body = {
        "id": str(uuid4()),
        "email": "test@example.com",
        "role": "student",
        "is_active": True,
        **patch,
        "first_name": "Тестовый",
        "last_name": "Пользователь",
    }
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=[body])
            ),
        ),
    )
    response = client.get("/admin/users/search/?q=тест")
    assert response.status_code == 503
    assert "test@example.com" not in response.content.decode()


def test_search_requires_staff(client, django_user_model):
    user = django_user_model.objects.create_user(username="ordinary")
    client.force_login(user)
    assert client.get("/admin/users/search/?q=Петров").status_code == 302


def test_search_returns_labels_and_uses_private_api(
    client, django_user_model, monkeypatch
):
    staff = django_user_model.objects.create_user(username="searcher", is_staff=True)
    client.force_login(staff)
    user_id = uuid4()
    original = httpx.Client

    def reply(request):
        assert request.url.path == "/internal/backoffice/users/search"
        assert request.url.params["q"] == "Петров"
        assert request.url.params["role"] == "student"
        assert request.url.params["active_only"] == "true"
        assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(user_id),
                    "email": "ivan@example.com",
                    "role": "student",
                    "is_active": True,
                    "last_name": "Петров",
                    "first_name": "Иван",
                    "middle_name": "Сергеевич",
                }
            ],
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(reply)),
    )
    response = client.get("/admin/users/search/?q=Петров")
    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"id": str(user_id), "label": "Петров Иван Сергеевич · ivan@example.com"}
        ]
    }
    assert "test-service-token" not in response.content.decode()
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("query", ["x", " " * 4, "x" * 201])
def test_search_rejects_invalid_query(client, django_user_model, query):
    staff = django_user_model.objects.create_user(username="bad-query", is_staff=True)
    client.force_login(staff)
    response = client.get("/admin/users/search/", {"q": query})
    assert response.status_code == 400


def test_search_failure_returns_safe_service_error(
    client, django_user_model, monkeypatch
):
    staff = django_user_model.objects.create_user(username="offline", is_staff=True)
    client.force_login(staff)
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(503, text="private-details")
            ),
        ),
    )
    response = client.get("/admin/users/search/?q=Петров")
    assert response.status_code == 503
    assert "private-details" not in response.content.decode()
