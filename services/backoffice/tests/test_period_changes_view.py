"""Проверяет формы смены класса с настоящим HTTP-клиентом и staff-аудитом."""

import json
from uuid import UUID

import httpx
import pytest
from django.test import Client

from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db
STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
URL = f"/admin/students/{STUDENT}/class/"
BASE = f"/internal/students/{STUDENT}/current-class-period"
PERIOD = {
    "id": 10,
    "student_id": str(STUDENT),
    "class_id": 1,
    "joined_at": "2026-09-01T12:00:00Z",
    "left_at": None,
}
DATA = {"operation": "transfer", "target_class_id": "2", "expected_period_id": "10"}


@pytest.fixture
def page(client, django_user_model, monkeypatch, settings):
    """Подменяет только HTTP-транспорт; view, формы, клиент и аудит настоящие."""
    settings.JOURNAL_BASE_URL = "http://journal.test"
    settings.JOURNAL_SERVICE_TOKEN = "journal-token"
    staff = django_user_model.objects.create_user(
        username="period-editor", is_staff=True
    )
    client.force_login(staff)
    original = httpx.Client
    requests = []
    state = {
        "current": dict(PERIOD),
        "outcome": "ok",
        "classes_down": False,
        "gateway_down": False,
    }

    def reply(request):
        requests.append(request)
        if request.url.host == "gateway.test":
            if state["gateway_down"]:
                raise httpx.ConnectError("offline", request=request)
            assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
            return httpx.Response(
                200,
                json={
                    "id": str(STUDENT),
                    "email": "student@example.com",
                    "role": "student",
                    "is_active": True,
                    "first_name": "Иван",
                    "last_name": "Петров",
                },
            )
        assert request.headers["authorization"] == "Bearer journal-token"
        if request.method == "GET" and request.url.path == "/internal/classes":
            if state["classes_down"]:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json=[
                    {
                        "id": number,
                        "name": name,
                        "study_year": 2026,
                        "created_at": "2026-09-01T00:00:00Z",
                    }
                    for number, name in ((1, "7А"), (2, "7Б"))
                ],
            )
        if request.method == "GET":
            assert request.url.path == BASE
            return (
                httpx.Response(404, json={})
                if state["current"] is None
                else httpx.Response(200, json=state["current"])
            )
        assert request.headers["x-actor-id"] == str(staff.pk)
        if state["outcome"] == "timeout":
            raise httpx.ReadTimeout("lost response", request=request)
        if state["outcome"] == "conflict":
            return httpx.Response(409)
        if request.method == "POST":
            assert request.url.path == BASE + "/transfer"
            body = json.loads(request.content)
            return httpx.Response(
                200, json={**PERIOD, "id": 11, "class_id": body["target_class_id"]}
            )
        assert request.method == "DELETE" and request.url.path == BASE
        return httpx.Response(204)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(reply)),
    )
    return client, staff, state, requests


def mutations(requests):
    """Выделяет отправленные команды, не смешивая их с загрузкой формы."""
    return [request for request in requests if request.method in ("POST", "DELETE")]


def test_get_shows_name_current_class_and_expected(page):
    """Форма показывает понятные данные, а скрытый ID относится к показанному периоду."""
    client, _, _, _ = page
    response = client.get(URL)
    assert response.status_code == 200
    html = response.content.decode()
    assert "Петров Иван" in html and "7А" in html and "7Б" in html
    assert response.context["form"].initial["expected_period_id"] == 10


def test_transfer_preserves_submitted_expected_and_trusted_actor(page):
    """Свежая загрузка страницы на POST не подменяет исходный expected формы."""
    client, staff, state, requests = page
    state["current"] = {**PERIOD, "id": 11, "class_id": 2}
    state["outcome"] = "conflict"
    response = client.post(URL, {**DATA, "actor_id": "999"})
    assert response.status_code == 200
    sent = mutations(requests)
    assert len(sent) == 1
    assert json.loads(sent[0].content) == {
        "target_class_id": 2,
        "expected_period_id": 10,
    }
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id and record.succeeded is False
    assert record.result_code == "journal_http_409"
    assert response.context["form"].data["expected_period_id"] == "10"
    assert response.context["can_submit"] is False
    assert "Обновить" in response.content.decode()


@pytest.mark.parametrize("operation", ["transfer", "end"])
def test_success_redirects_and_audits_staff(page, operation):
    """Обе операции записывают фактического сотрудника, не actor_id из формы."""
    client, staff, _, requests = page
    data = (
        DATA
        if operation == "transfer"
        else {"operation": "end", "expected_period_id": "10", "confirm_end": "on"}
    )
    response = client.post(URL, {**data, "actor_id": "999"})
    assert response.status_code == 302 and response.url == URL
    sent = mutations(requests)
    assert len(sent) == 1
    assert sent[0].method == ("POST" if operation == "transfer" else "DELETE")
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.id and record.succeeded is True
    assert record.target_ids["expected_period_id"] == 10


@pytest.mark.parametrize(
    "data",
    [
        {"operation": "end", "expected_period_id": "10"},
        {"operation": "transfer", "expected_period_id": "10", "target_class_id": "999"},
        {"operation": "transfer", "target_class_id": "2"},
        {"operation": "delete-user", "expected_period_id": "10"},
    ],
)
def test_invalid_form_sends_no_command(page, data):
    """Подтверждение завершения, known choice и expected обязательны."""
    client, _, _, requests = page
    response = client.post(URL, data)
    assert response.status_code == 200
    assert not mutations(requests)
    assert not AdminActionRecord.objects.exists()


def test_timeout_is_unknown_result_and_requires_refresh(page):
    """Не заявляет об отмене перевода после потери ответа и не повторяет запрос."""
    client, _, state, requests = page
    state["outcome"] = "timeout"
    response = client.post(URL, DATA)
    assert response.status_code == 200
    assert len(mutations(requests)) == 1
    assert response.context["can_submit"] is False
    assert "неизвестен" in response.content.decode().lower()
    assert AdminActionRecord.objects.get().result_code == "journal_result_unknown"


def test_end_does_not_require_gateway_or_available_class_choices(page):
    """Закрыть локальный период можно при недоступном владельце users/списке классов."""
    client, _, state, requests = page
    state["gateway_down"] = True
    state["classes_down"] = True
    response = client.post(
        URL,
        {
            "operation": "end",
            "expected_period_id": "10",
            "confirm_end": "on",
            "target_class_id": "2",
        },
    )
    assert response.status_code == 302
    assert len(mutations(requests)) == 1 and mutations(requests)[0].method == "DELETE"


def test_absent_current_has_no_new_submission(page):
    """Пустое состояние не подставляет выдуманный expected и не отправляет команду."""
    client, _, state, requests = page
    state["current"] = None
    response = client.get(URL)
    assert response.status_code == 200
    assert response.context["can_submit"] is False
    assert not mutations(requests)


def test_staff_and_csrf_are_required(page, django_user_model):
    """Прямой URL и POST без CSRF не обходят защиту Django Admin."""
    _, staff, _, requests = page
    anonymous = Client()
    assert anonymous.get(URL).status_code == 302
    secure = Client(enforce_csrf_checks=True)
    secure.force_login(staff)
    assert secure.post(URL, DATA).status_code == 403
    ordinary = django_user_model.objects.create_user(username="ordinary-student")
    anonymous.force_login(ordinary)
    assert anonymous.get(URL).status_code == 302
    assert not mutations(requests)
