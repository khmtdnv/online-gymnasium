"""Проверяет HTTP-контракт чтения классов и добавления ученика в Journal."""

import json
from uuid import UUID

import httpx
import pytest

STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
PERIOD = {
    "id": 123,
    "student_id": str(STUDENT),
    "class_id": 10,
    "joined_at": "2026-10-15T12:00:00Z",
    "left_at": None,
}


def client_types():
    """Импортирует реальные компоненты, не подменяя проверку ответа."""
    from backoffice_admin.journal_client import (
        JournalBackofficeClient,
        JournalProtocolError,
    )

    return JournalBackofficeClient, JournalProtocolError


def school_class(class_id):
    """Возвращает пример полного ответа Journal о классе."""
    return {
        "id": class_id,
        "name": f"8А-{class_id}",
        "study_year": 2026,
        "created_at": "2026-10-15T12:00:00Z",
    }


def test_list_classes_loads_all_pages_and_uses_separate_bearer():
    """Не обрезает список на первой странице и не использует секрет Gateway."""
    client_type, _ = client_types()
    requests = []

    def reply(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer journal-token"
        assert request.url.path == "/internal/classes"
        assert request.url.params["limit"] == "100"
        offset = int(request.url.params["offset"])
        return httpx.Response(
            200,
            json=[school_class(i) for i in range(1, 101)]
            if offset == 0
            else [school_class(101)],
        )

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        classes = client_type(http, "journal-token").list_classes()
    assert [row.id for row in classes] == list(range(1, 102))
    assert [request.url.params["offset"] for request in requests] == ["0", "100"]


@pytest.mark.parametrize(
    "payload", [{}, [{"id": "bad"}], [school_class(1), school_class(1)]]
)
def test_list_rejects_invalid_or_duplicate_classes(payload):
    client_type, protocol_error = client_types()
    with (
        httpx.Client(
            base_url="http://journal",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        ) as http,
        pytest.raises(protocol_error),
    ):
        client_type(http, "journal-token").list_classes()


def test_repeated_page_does_not_loop_forever():
    client_type, protocol_error = client_types()
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json=[school_class(i) for i in range(1, 101)])

    with (
        httpx.Client(
            base_url="http://journal", transport=httpx.MockTransport(reply)
        ) as http,
        pytest.raises(protocol_error),
    ):
        client_type(http, "journal-token").list_classes()
    assert len(calls) == 2


@pytest.mark.parametrize(("status", "created"), [(201, True), (200, False)])
def test_add_sends_identity_and_validates_response(status, created):
    client_type, _ = client_types()

    def reply(request):
        assert request.method == "PUT"
        assert request.url.path == f"/internal/students/{STUDENT}/current-class-period"
        assert request.headers["authorization"] == "Bearer journal-token"
        assert request.headers["x-actor-id"] == "42"
        assert json.loads(request.content) == {"class_id": 10}
        return httpx.Response(status, json=PERIOD)

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        result = client_type(http, "journal-token").add_student_to_class(
            STUDENT, 10, "42"
        )
    assert result.created is created
    assert result.period.id == 123 and result.period.student_id == STUDENT


@pytest.mark.parametrize("status", [401, 403, 404, 409, 422, 503, 302])
def test_add_propagates_http_errors_without_retry(status):
    client_type, _ = client_types()
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(status)

    with (
        httpx.Client(
            base_url="http://journal", transport=httpx.MockTransport(reply)
        ) as http,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client_type(http, "journal-token").add_student_to_class(STUDENT, 10, "42")
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (204, None),
        (202, PERIOD),
        (200, {}),
        (201, {**PERIOD, "class_id": 20}),
        (201, {**PERIOD, "student_id": "bbbbbbbb-0000-4000-8000-000000000002"}),
        (201, {**PERIOD, "id": True}),
        (201, {**PERIOD, "left_at": "2026-10-15T13:00:00Z"}),
        (201, {**PERIOD, "joined_at": "2026-10-15T12:00:00"}),
    ],
)
def test_add_rejects_wrong_success_status_or_contract(status, payload):
    client_type, protocol_error = client_types()
    with (
        httpx.Client(
            base_url="http://journal",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json=payload)
            ),
        ) as http,
        pytest.raises(protocol_error),
    ):
        client_type(http, "journal-token").add_student_to_class(STUDENT, 10, "42")


def test_add_does_not_hide_network_failure():
    client_type, _ = client_types()

    def fail(request):
        raise httpx.ReadTimeout("test", request=request)

    with (
        httpx.Client(
            base_url="http://journal", transport=httpx.MockTransport(fail)
        ) as http,
        pytest.raises(httpx.ReadTimeout),
    ):
        client_type(http, "journal-token").add_student_to_class(STUDENT, 10, "42")
