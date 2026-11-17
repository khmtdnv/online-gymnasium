"""Staff/CSRF, серверный actor и исходы действий через настоящий Journal client."""

from urllib.parse import urlencode

import httpx
import pytest

from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db
URL = "/admin/teacher-classes/"
TEACHER = "8df96b7a-7d30-44e7-b577-f6581300e101"
CLASS = {
    "id": 7,
    "name": "7А",
    "study_year": 2026,
    "created_at": "2026-10-17T10:00:00Z",
}


@pytest.fixture
def page(client, django_user_model, settings, monkeypatch):
    settings.JOURNAL_BASE_URL = "http://journal.test"
    settings.JOURNAL_SERVICE_TOKEN = "journal-token"
    staff = django_user_model.objects.create_user(
        username="teacher-staff", is_staff=True
    )
    client.force_login(staff)
    from backoffice_admin import teacher_class_views

    original = httpx.Client

    def install(reply):
        monkeypatch.setattr(
            teacher_class_views,
            "_journal_http",
            lambda: original(
                base_url="http://journal.test", transport=httpx.MockTransport(reply)
            ),
        )

    return client, staff, install


@pytest.mark.parametrize(
    "action,status,code",
    [
        ("assign", 201, "created"),
        ("assign", 204, "already_exists"),
        ("remove", 204, "removed"),
    ],
)
def test_valid_post_records_server_actor_and_redirects(page, action, status, code):
    client, staff, install = page

    def reply(request):
        if request.url.path == "/internal/classes":
            return httpx.Response(200, json=[CLASS])
        assert request.headers["x-actor-id"] == str(staff.pk)
        assert request.method == ("PUT" if action == "assign" else "DELETE")
        return httpx.Response(status)

    install(reply)
    response = client.post(
        URL, {"teacher_id": TEACHER, "class_id": 7, "action": action, "actor_id": "999"}
    )
    assert response.status_code == 302
    record = AdminActionRecord.objects.get()
    assert record.actor_id == staff.pk and record.succeeded
    assert record.result_code == code
    assert record.target_ids == {"teacher_id": TEACHER, "class_id": 7}


def test_remove_does_not_need_global_classes_or_gateway(page):
    client, _, install = page

    def reply(request):
        assert request.method == "DELETE"
        return httpx.Response(204)

    install(reply)
    assert (
        client.post(
            URL, {"teacher_id": TEACHER, "class_id": 7, "action": "remove"}
        ).status_code
        == 302
    )


def test_timeout_records_unknown_not_success(page):
    client, _, install = page

    def reply(request):
        if request.method == "GET":
            return httpx.Response(200, json=[CLASS])
        raise httpx.ReadTimeout("lost", request=request)

    install(reply)
    response = client.post(
        URL, {"teacher_id": TEACHER, "class_id": 7, "action": "assign"}
    )
    assert response.status_code == 200
    assert "неизвестен" in response.content.decode()
    record = AdminActionRecord.objects.get()
    assert not record.succeeded and record.result_code == "journal_result_unknown"


def test_invalid_choice_and_missing_service_never_write(page, settings):
    client, _, install = page
    methods = []

    def reply(request):
        methods.append(request.method)
        return httpx.Response(200, json=[CLASS])

    install(reply)
    assert (
        client.post(
            URL, {"teacher_id": TEACHER, "class_id": 8, "action": "assign"}
        ).status_code
        == 200
    )
    assert set(methods) == {"GET"}
    assert not AdminActionRecord.objects.exists()
    settings.JOURNAL_SERVICE_TOKEN = ""
    assert (
        client.post(
            URL, {"teacher_id": TEACHER, "class_id": 7, "action": "remove"}
        ).status_code
        == 200
    )
    assert not AdminActionRecord.objects.exists()


def test_get_shows_named_assigned_classes_and_search(page):
    client, _, install = page
    install(lambda _: httpx.Response(200, json=[CLASS]))
    response = client.get(URL + "?" + urlencode({"teacher_id": TEACHER}))
    assert response.status_code == 200
    html = response.content.decode()
    assert "7А" in html and "2026/2027" in html
    assert "Найти преподавателя" in html


def test_staff_and_csrf_are_required(client, django_user_model):
    assert client.get(URL).status_code == 302
    assert client.get("/admin/teachers/search/?q=Петров").status_code == 302
    from django.test import Client

    user = django_user_model.objects.create_user(username="teacher-csrf", is_staff=True)
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(user)
    assert (
        browser.post(
            URL, {"teacher_id": TEACHER, "class_id": 7, "action": "assign"}
        ).status_code
        == 403
    )


def test_error_after_unknown_write_does_not_claim_nothing_was_sent(page):
    client, _, install = page
    gets = 0

    def reply(request):
        nonlocal gets
        if request.method == "GET":
            gets += 1
            if gets > 1:
                return httpx.Response(503)
            return httpx.Response(200, json=[CLASS])
        raise httpx.ReadTimeout("lost", request=request)

    install(reply)
    html = client.post(
        URL, {"teacher_id": TEACHER, "class_id": 7, "action": "assign"}
    ).content.decode()
    assert "неизвестен" in html
    assert "Записи не отправлены" not in html


@pytest.mark.parametrize(
    "role,active,status",
    [("teacher", True, 200), ("student", True, 503), ("teacher", False, 503)],
)
def test_teacher_search_passes_role_filter_and_rejects_wrong_response(
    page, monkeypatch, role, active, status
):
    client, _, _ = page
    from backoffice_admin import teacher_class_views

    original = httpx.Client

    def reply(request):
        assert request.url.params["role"] == "teacher"
        assert request.url.params["active_only"] == "true"
        return httpx.Response(
            200,
            json=[
                {
                    "id": TEACHER,
                    "email": "teacher@example.test",
                    "first_name": "Иван",
                    "last_name": "Петров",
                    "middle_name": "",
                    "role": role,
                    "is_active": active,
                }
            ],
        )

    monkeypatch.setattr(
        teacher_class_views.httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(reply)),
    )
    response = client.get("/admin/teachers/search/?q=Петров")
    assert response.status_code == status
    assert "no-store" in response["Cache-Control"]
    if status == 200:
        assert response.json()["results"][0]["id"] == TEACHER


def test_general_user_search_offers_assignments_for_inactive_teacher(page, monkeypatch):
    client, _, _ = page
    from backoffice_admin import user_views

    original = httpx.Client

    def reply(_):
        return httpx.Response(
            200,
            json=[
                {
                    "id": TEACHER,
                    "email": "teacher@example.test",
                    "first_name": "Иван",
                    "last_name": "Петров",
                    "middle_name": "",
                    "role": "teacher",
                    "is_active": False,
                }
            ],
        )

    monkeypatch.setattr(
        user_views,
        "_client",
        lambda: original(
            base_url="http://gateway.test", transport=httpx.MockTransport(reply)
        ),
    )
    response = client.get("/admin/users/?q=Петров")
    assert response.status_code == 200
    assert f"/admin/teacher-classes/?teacher_id={TEACHER}" in response.content.decode()


def test_failed_removal_preserves_error_but_restores_full_assignment_choices(page):
    client, _, install = page

    def reply(request):
        if request.method == "DELETE":
            raise httpx.ReadTimeout("lost", request=request)
        if request.url.path == "/internal/classes":
            return httpx.Response(200, json=[CLASS, {**CLASS, "id": 8, "name": "7Б"}])
        return httpx.Response(200, json=[CLASS])

    install(reply)
    response = client.post(
        URL, {"teacher_id": TEACHER, "class_id": 7, "action": "remove"}
    )
    assert response.status_code == 200
    assert "неизвестен" in response.content.decode()
    choices = list(response.context["assignment_form"].fields["class_id"].choices)
    assert choices == [
        ("", "Выберите класс"),
        (7, "7А · 2026/2027"),
        (8, "7Б · 2026/2027"),
    ]
    assert '<option value="8">7Б · 2026/2027</option>' in response.content.decode()
    assert response.context["can_assign"] is True
