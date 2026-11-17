"""Проверяет команды Journal и недоверенные успешные HTTP-ответы."""

import json
from uuid import UUID

import httpx
import pytest

from backoffice_admin.journal_client import (
    JournalBackofficeClient,
    JournalProtocolError,
)

STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
BASE = f"/internal/students/{STUDENT}/current-class-period"
PERIOD = {
    "id": 11,
    "student_id": str(STUDENT),
    "class_id": 2,
    "joined_at": "2026-10-16T12:00:00Z",
    "left_at": None,
}


def test_transfer_sends_expected_and_actor_and_validates_period():
    """Потеря expected в HTTP-запросе лишит форму защиты от устаревания."""

    def reply(request):
        assert request.method == "POST" and request.url.path == BASE + "/transfer"
        assert request.headers["authorization"] == "Bearer journal-token"
        assert request.headers["x-actor-id"] == "42"
        assert json.loads(request.content) == {
            "target_class_id": 2,
            "expected_period_id": 10,
        }
        return httpx.Response(200, json=PERIOD)

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        result = JournalBackofficeClient(
            http, "journal-token"
        ).transfer_student_to_class(STUDENT, 2, 10, "42")
    assert result.id == 11 and result.class_id == 2


@pytest.mark.parametrize(
    "payload",
    [
        {**PERIOD, "student_id": "bbbbbbbb-0000-4000-8000-000000000002"},
        {**PERIOD, "class_id": 3},
        {**PERIOD, "left_at": "2026-10-16T13:00:00Z"},
        {},
        [],
        {**PERIOD, "id": True},
    ],
)
def test_transfer_rejects_inconsistent_success(payload):
    """Успешный статус не делает чужой или закрытый период допустимым."""
    with (
        httpx.Client(
            base_url="http://journal",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        ) as http,
        pytest.raises(JournalProtocolError),
    ):
        JournalBackofficeClient(http, "journal-token").transfer_student_to_class(
            STUDENT, 2, 10, "42"
        )


@pytest.mark.parametrize("status", [201, 202, 204])
def test_transfer_rejects_unexpected_success_status(status):
    """Только200 подтверждает согласованный контракт перевода."""
    with (
        httpx.Client(
            base_url="http://journal",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json=PERIOD)
            ),
        ) as http,
        pytest.raises(JournalProtocolError),
    ):
        JournalBackofficeClient(http, "journal-token").transfer_student_to_class(
            STUDENT, 2, 10, "42"
        )


def test_end_sends_expected_as_query_and_accepts_empty204():
    """DELETE использует expected, не отправляя служебный actor в теле."""

    def reply(request):
        assert request.method == "DELETE" and request.url.path == BASE
        assert request.url.params["expected_period_id"] == "10"
        assert request.headers["x-actor-id"] == "42"
        assert request.headers["authorization"] == "Bearer journal-token"
        assert request.content == b""
        return httpx.Response(204)

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        assert (
            JournalBackofficeClient(http, "journal-token").end_student_class_period(
                STUDENT, 10, "42"
            )
            is None
        )


@pytest.mark.parametrize("status,body", [(200, b""), (204, b"{}"), (202, b"")])
def test_end_rejects_unexpected_status_or_body(status, body):
    """Тело у204 или иной статус не подтверждают ожидаемое завершение."""
    with (
        httpx.Client(
            base_url="http://journal",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, content=body)
            ),
        ) as http,
        pytest.raises(JournalProtocolError),
    ):
        JournalBackofficeClient(http, "journal-token").end_student_class_period(
            STUDENT, 10, "42"
        )


@pytest.mark.parametrize("status", [200, 404])
def test_current_period_reads_open_or_absent(status):
    """404 означает отсутствие открытого периода, а не отсутствие пользователя."""

    def reply(request):
        assert request.method == "GET" and request.url.path == BASE
        assert request.headers["authorization"] == "Bearer journal-token"
        return httpx.Response(status, json=PERIOD if status == 200 else {})

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        result = JournalBackofficeClient(
            http, "journal-token"
        ).get_current_period_for_student(STUDENT)
    assert result.id == 11 if status == 200 else result is None


@pytest.mark.parametrize("action", ["transfer", "end", "current"])
@pytest.mark.parametrize("failure", ["status", "timeout"])
def test_errors_and_timeouts_propagate_without_automatic_retry(action, failure):
    """Не повторяет потенциально выполненную команду после потери ответа."""
    calls = []

    def reply(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(409)

    with httpx.Client(
        base_url="http://journal", transport=httpx.MockTransport(reply)
    ) as http:
        client = JournalBackofficeClient(http, "journal-token")
        with pytest.raises(
            httpx.HTTPStatusError if failure == "status" else httpx.ReadTimeout
        ):
            if action == "transfer":
                client.transfer_student_to_class(STUDENT, 2, 10, "42")
            elif action == "end":
                client.end_student_class_period(STUDENT, 10, "42")
            else:
                client.get_current_period_for_student(STUDENT)
    assert len(calls) == 1
