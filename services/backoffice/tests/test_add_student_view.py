"""Проверяет страницу, доступ, журнал и HTTP-сценарий добавления ученика."""

import json
from uuid import UUID

import httpx
import pytest
from django.urls import reverse

from backoffice_admin.journal_client import (
    AddStudentToClassResult,
    JournalBackofficeClient,
    JournalClassPeriod,
    JournalProtocolError,
)
from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db
URL = "/admin/add-student-to-class/"
STUDENT = "aaaaaaaa-0000-4000-8000-000000000001"
DATA = {"student_id": STUDENT, "class_id": "10"}


@pytest.mark.parametrize(
    "outcome", ["created", "existing", "conflict", "wrong_student"]
)
def test_form_uses_real_journal_client_and_records_http_outcome(page, outcome):
    """Не подменяет PUT-метод: проверяет сборку запроса, разбор ответа и журнал."""
    client, staff, install, requests = page

    def reply(request):
        assert request.headers["authorization"] == "Bearer journal-token"
        if request.method == "GET":
            assert request.url.path == "/internal/classes"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 10,
                        "name": "8А",
                        "study_year": 2026,
                        "created_at": "2026-10-15T12:00:00Z",
                    }
                ],
            )
        assert request.method == "PUT"
        assert request.url.path == f"/internal/students/{STUDENT}/current-class-period"
        assert request.headers["x-actor-id"] == str(staff.pk)
        assert json.loads(request.content) == {"class_id": 10}
        if outcome == "conflict":
            return httpx.Response(409)
        return httpx.Response(
            200 if outcome == "existing" else 201,
            json={
                "id": 123,
                "student_id": "bbbbbbbb-0000-4000-8000-000000000002"
                if outcome == "wrong_student"
                else STUDENT,
                "class_id": 10,
                "joined_at": "2026-10-15T12:00:00Z",
                "left_at": None,
            },
        )

    install(reply)
    response = client.post(URL, {**DATA, "actor_id": "999"})
    assert [request.method for request in requests] == ["GET", "PUT"]
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.pk
    assert record.action == "add_student_to_class"
    if outcome in {"created", "existing"}:
        assert response.status_code == 302 and response.url == URL
        assert record.succeeded is True
        assert record.result_code == (
            "created" if outcome == "created" else "already_exists"
        )
        assert record.target_ids == {
            "student_id": STUDENT,
            "class_id": 10,
            "period_id": 123,
        }
    else:
        assert response.status_code == 200
        assert record.succeeded is False
        assert record.result_code == (
            "journal_http_409" if outcome == "conflict" else "journal_protocol_error"
        )
        assert dict(response.context["form"].data.items()) == {
            **DATA,
            "actor_id": "999",
        }
        assert response.context["form"].non_field_errors()


@pytest.fixture
def page(client, django_user_model, monkeypatch, settings):
    settings.JOURNAL_BASE_URL = "http://journal.test"
    settings.JOURNAL_SERVICE_TOKEN = "journal-token"
    staff = django_user_model.objects.create_user(username="class-staff", is_staff=True)
    client.force_login(staff)
    original = httpx.Client
    requests = []

    def install(reply):
        def send(request):
            requests.append(request)
            return reply(request)

        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(send)),
        )

    def classes(request):
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer journal-token"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 10,
                    "name": "8А",
                    "study_year": 2026,
                    "created_at": "2026-10-15T12:00:00Z",
                }
            ],
        )

    install(classes)
    return client, staff, install, requests


def test_get_shows_named_classes_and_csrf(page):
    client, _, _, requests = page
    response = client.get(URL)
    assert response.status_code == 200
    assert reverse("backoffice-add-student-to-class") == URL
    text = response.content.decode()
    assert "8А · 2026/2027" in text
    assert 'name="csrfmiddlewaretoken"' in text
    assert 'name="actor_id"' not in text
    assert len(requests) == 1
    assert not AdminActionRecord.objects.exists()


@pytest.mark.parametrize("created", [True, False])
def test_success_uses_authenticated_staff_and_records_outcome(
    page, monkeypatch, created
):
    client, staff, _, _ = page
    calls = []

    def add(self, student_id, class_id, actor_id):
        calls.append((student_id, class_id, actor_id))
        return AddStudentToClassResult(
            period=JournalClassPeriod(
                id=123,
                student_id=STUDENT,
                class_id=10,
                joined_at="2026-10-15T12:00:00Z",
                left_at=None,
            ),
            created=created,
        )

    monkeypatch.setattr(JournalBackofficeClient, "add_student_to_class", add)
    response = client.post(URL, {**DATA, "actor_id": "999"})
    assert response.status_code == 302 and response.url == URL
    assert calls == [(UUID(STUDENT), 10, str(staff.pk))]
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.pk
    assert record.action == "add_student_to_class"
    assert record.target_ids == {
        "student_id": STUDENT,
        "class_id": 10,
        "period_id": 123,
    }
    assert record.succeeded is True
    assert record.result_code == ("created" if created else "already_exists")
    html = client.get(URL).content.decode()
    assert (
        "Ученик добавлен в класс." if created else "Ученик уже состоит в этом классе."
    ) in html
    assert AdminActionRecord.objects.count() == 1


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "Ученик или класс не найден"),
        (409, "Ученик уже состоит в другом классе"),
        (422, "Пользователь должен быть активным учеником"),
        (503, "Journal временно недоступен"),
        (403, "Journal отклонил служебный запрос"),
    ],
)
def test_http_error_preserves_input_and_records_failure(
    page, monkeypatch, status, message
):
    client, staff, _, _ = page

    def fail(*args, **kwargs):
        response = httpx.Response(
            status, request=httpx.Request("PUT", "http://journal.test")
        )
        response.raise_for_status()

    monkeypatch.setattr(JournalBackofficeClient, "add_student_to_class", fail)
    response = client.post(URL, DATA)
    assert response.status_code == 200
    assert message in response.content.decode()
    assert dict(response.context["form"].data.items()) == DATA
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.pk and record.succeeded is False
    assert record.result_code == f"journal_http_{status}"


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("private"), JournalProtocolError("private")]
)
def test_unknown_result_is_not_claimed_as_definite_rejection(page, monkeypatch, error):
    client, _, _, _ = page

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(JournalBackofficeClient, "add_student_to_class", fail)
    response = client.post(URL, DATA)
    assert response.status_code == 200
    assert "Проверьте текущий класс" in response.content.decode()
    assert b"private" not in response.content
    record = AdminActionRecord.objects.get()
    assert record.succeeded is False
    assert record.result_code in {"journal_result_unknown", "journal_protocol_error"}


@pytest.mark.parametrize(
    "body", [{**DATA, "student_id": "bad"}, {**DATA, "class_id": "20"}]
)
def test_invalid_form_never_sends_put(page, monkeypatch, body):
    client, _, _, _ = page

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid form must not call PUT")

    monkeypatch.setattr(JournalBackofficeClient, "add_student_to_class", unexpected)
    response = client.post(URL, body)
    assert response.status_code == 200 and response.context["form"].errors
    assert not AdminActionRecord.objects.exists()


def test_class_load_failure_disables_submission_and_does_not_audit_command(page):
    client, _, install, _ = page
    install(lambda request: httpx.Response(503, text="private upstream"))
    response = client.post(URL, DATA)
    assert response.status_code == 200
    assert "Не удалось загрузить классы" in response.content.decode()
    assert 'value="10" selected' in str(response.context["form"]["class_id"])
    assert not response.context["form"].errors
    assert "disabled" in response.content.decode()
    assert b"private upstream" not in response.content
    assert not AdminActionRecord.objects.exists()


def test_missing_settings_do_not_contact_other_service(page, settings):
    client, _, _, requests = page
    settings.JOURNAL_SERVICE_TOKEN = ""
    response = client.get(URL)
    assert response.status_code == 200
    assert "Подключение к Journal не настроено" in response.content.decode()
    assert requests == []


def test_empty_class_list_has_explanation_and_disabled_button(page):
    client, _, install, _ = page
    install(lambda request: httpx.Response(200, json=[]))
    response = client.get(URL)
    assert "В Journal пока нет классов" in response.content.decode()
    assert "disabled" in response.content.decode()


@pytest.mark.parametrize("user_kind", ["anonymous", "regular", "inactive"])
def test_nonstaff_cannot_get_or_submit_form(page, django_user_model, user_kind):
    client, _, _, requests = page
    client.logout()
    if user_kind != "anonymous":
        user = django_user_model.objects.create_user(
            username="no-access",
            is_staff=user_kind == "inactive",
            is_active=user_kind != "inactive",
        )
        client.force_login(user)
    for response in (client.get(URL), client.post(URL, DATA)):
        assert response.status_code == 302 and "/admin/login/" in response.url
    assert requests == []
    assert not AdminActionRecord.objects.exists()
