"""Проверяет закрытый поиск и изменение ФИО без раскрытия хеша пароля."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_backoffice_api import make_app, request

from gateway_service.domain.user import Role, User

HEADERS = {"X-Backoffice-Service-Token": "test-backoffice-token"}


def test_create_stores_names_without_exposing_password():
    users = SimpleNamespace(create_user=AsyncMock())
    app, _ = make_app(users)
    response = request(
        app,
        "POST",
        headers=HEADERS,
        json={
            "email": "ivan@example.com",
            "password": "secret",
            "role": "student",
            "first_name": " Иван ",
            "last_name": "Петров",
            "middle_name": "Сергеевич",
        },
    )
    assert response.status_code == 201
    stored = users.create_user.await_args.args[0]
    assert stored.first_name == "Иван" and stored.last_name == "Петров"
    assert response.json()["middle_name"] == "Сергеевич"
    assert "password" not in response.text


def test_update_returns_new_profile_after_successful_uow_exit():
    user = User(
        uuid4(), "ivan@example.com", Role.STUDENT, "secret", True, "Иван", "Петров", ""
    )
    users = SimpleNamespace(update_user_names=AsyncMock(return_value=user))
    app, factory = make_app(users)
    response = request(
        app,
        "PUT",
        path=f"/internal/backoffice/users/{user.id}/name",
        headers=HEADERS,
        json={"first_name": "Иван", "last_name": "Петров"},
    )
    assert response.status_code == 200
    assert response.json()["first_name"] == "Иван"
    assert "password" not in response.text
    factory.return_value.__aexit__.assert_awaited_once()


def test_search_passes_terms_and_student_filter_to_repository():
    """Передаёт фильтры и возвращает безопасный ограниченный список."""
    user = User(
        uuid4(),
        "ivan@example.com",
        Role.STUDENT,
        "secret-hash",
        True,
        first_name="Тестовый",
        last_name="Пользователь",
    )
    users = SimpleNamespace(search_users=AsyncMock(return_value=[user]))
    app, _ = make_app(users)
    response = request(
        app,
        "GET",
        path="/internal/backoffice/users/search?q=Петр%20Ив&role=student&active_only=true",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(user.id)
    assert "password_hash" not in response.text
    users.search_users.assert_awaited_once_with("Петр Ив", Role.STUDENT, True, 20)


@pytest.mark.parametrize("query", ["x", " " * 3, "x" * 201])
def test_search_rejects_invalid_length_before_repository(query):
    """Короткий или чрезмерный запрос не запускает поиск."""
    from urllib.parse import urlencode

    users = SimpleNamespace(search_users=AsyncMock(return_value=[]))
    app, _ = make_app(users)
    response = request(
        app,
        "GET",
        path="/internal/backoffice/users/search?" + urlencode({"q": query}),
        headers=HEADERS,
    )
    assert response.status_code == 422
    users.search_users.assert_not_awaited()


def test_profile_update_normalizes_names_and_returns_not_found():
    """Передаёт обрезанные имена в UPDATE; отсутствующий ID даёт 404."""
    user_id = uuid4()
    users = SimpleNamespace(update_user_names=AsyncMock(return_value=None))
    app, _ = make_app(users)
    response = request(
        app,
        "PUT",
        path=f"/internal/backoffice/users/{user_id}/name",
        headers=HEADERS,
        json={"first_name": " Иван ", "last_name": " Петров ", "middle_name": ""},
    )
    assert response.status_code == 404
    users.update_user_names.assert_awaited_once_with(user_id, "Иван", "Петров", "")


def test_profile_requires_service_authentication():
    users = SimpleNamespace(search_users=AsyncMock())
    app, factory = make_app(users)
    response = request(app, "GET", path="/internal/backoffice/users/search?q=Петров")
    assert response.status_code == 403
    factory.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"first_name": " ", "last_name": "Петров"},
        {"first_name": "Иван", "last_name": "Петров", "middle_name": "x" * 101},
    ],
)
def test_profile_rejects_invalid_names(body):
    users = SimpleNamespace(update_user_names=AsyncMock())
    app, _ = make_app(users)
    response = request(
        app,
        "PUT",
        path=f"/internal/backoffice/users/{uuid4()}/name",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 422
    users.update_user_names.assert_not_awaited()
