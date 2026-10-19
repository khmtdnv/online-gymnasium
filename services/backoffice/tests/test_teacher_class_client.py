"""Проверяет новые методы настоящих HTTP-клиентов на контролируемом транспорте."""

from uuid import UUID

import httpx
import pytest

from backoffice_admin.gateway_client import (
    GatewayBackofficeClient,
    GatewayProtocolError,
)
from backoffice_admin.journal_client import (
    JournalBackofficeClient,
    JournalProtocolError,
)

TEACHER = UUID("8df96b7a-7d30-44e7-b577-f6581300e101")


@pytest.mark.parametrize("status,expected", [(201, True), (204, False)])
def test_assign_serializes_pair_and_server_actor(status, expected):
    def reply(request):
        assert request.method == "PUT"
        assert request.url.path == f"/internal/teachers/{TEACHER}/classes/7"
        assert request.headers["authorization"] == "Bearer journal-token"
        assert request.headers["x-actor-id"] == "42"
        assert request.content == b""
        return httpx.Response(status)

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        assert (
            JournalBackofficeClient(http, "journal-token").assign_teacher_to_class(
                TEACHER, 7, "42"
            )
            is expected
        )


@pytest.mark.parametrize("status,content", [(200, b""), (201, b"{}"), (204, b"bad")])
def test_unexpected_assignment_response_is_protocol_error(status, content):
    with (
        httpx.Client(
            base_url="http://journal",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(status, content=content)
            ),
        ) as http,
        pytest.raises(JournalProtocolError),
    ):
        JournalBackofficeClient(http, "token").assign_teacher_to_class(TEACHER, 7, "42")


def test_remove_and_list_preserve_contract():
    def reply(request):
        if request.method == "DELETE":
            return httpx.Response(204)
        assert request.url.path == f"/internal/teachers/{TEACHER}/classes"
        return httpx.Response(200, json=[])

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        client = JournalBackofficeClient(http, "token")
        assert client.unassign_teacher_from_class(TEACHER, 7, "42") is None
        assert client.list_classes_for_teacher(TEACHER) == []


@pytest.mark.parametrize("returned_role", ["teacher", "student"])
def test_teacher_search_filter_is_enforced(returned_role):
    def reply(request):
        assert request.url.params["role"] == "teacher"
        assert request.url.params["active_only"] == "true"
        return httpx.Response(
            200,
            json=[
                {
                    "id": str(TEACHER),
                    "email": "teacher@example.test",
                    "role": returned_role,
                    "is_active": True,
                    "first_name": "Иван",
                    "last_name": "Петров",
                    "middle_name": "",
                }
            ],
        )

    with httpx.Client(
        base_url="http://gateway", transport=httpx.MockTransport(reply)
    ) as http:
        client = GatewayBackofficeClient(http, "token")
        if returned_role == "teacher":
            assert client.search_users("Петров", role="teacher")[0].id == TEACHER
        else:
            with pytest.raises(GatewayProtocolError):
                client.search_users("Петров", role="teacher")


def test_conflicting_search_filters_do_not_send_request():
    def unexpected(_):
        raise AssertionError("must not call Gateway")

    with (
        httpx.Client(
            base_url="http://gateway", transport=httpx.MockTransport(unexpected)
        ) as http,
        pytest.raises(ValueError),
    ):
        GatewayBackofficeClient(http, "token").search_users(
            "Петров", students_only=True, role="teacher"
        )


@pytest.mark.parametrize(
    "mode", ["valid", "duplicate", "unordered", "too_many", "malformed"]
)
def test_teacher_classes_pagination_is_bounded_and_ordered(mode):
    def item(i):
        return {
            "id": i,
            "name": "7А",
            "study_year": 2026,
            "created_at": "2026-10-17T10:00:00Z",
        }

    def reply(request):
        offset = int(request.url.params["offset"])
        assert request.url.params["limit"] == "100"
        if mode == "malformed":
            return httpx.Response(200, json={})
        if mode == "too_many":
            return httpx.Response(200, json=[item(i) for i in range(1, 102)])
        if mode == "unordered":
            return httpx.Response(200, json=[item(2), item(1)])
        if offset == 0:
            return httpx.Response(200, json=[item(i) for i in range(1, 101)])
        assert offset == 100
        return httpx.Response(200, json=[item(101 if mode == "valid" else 100)])

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        client = JournalBackofficeClient(http, "token")
        if mode == "valid":
            assert [x.id for x in client.list_classes_for_teacher(TEACHER)] == list(
                range(1, 102)
            )
        else:
            with pytest.raises(JournalProtocolError):
                client.list_classes_for_teacher(TEACHER)
