"""Внешняя ошибка не должна становиться ложным отсутствием данных."""

import asyncio
from uuid import UUID

import httpx
import pytest

from homework_service.application.ports.errors import OwnerLookupUnavailableError
from homework_service.infrastructure.journal_client import HttpJournalReader
from homework_service.infrastructure.schedule_client import HttpScheduleReader

PERIOD = {
    "id": 1,
    "class_id": 7,
    "student_id": str(UUID(int=1)),
    "joined_at": "2026-09-01T10:00:00Z",
    "left_at": None,
}
LESSON = {
    "id": 22,
    "class_id": 7,
    "subject_id": 3,
    "teacher_id": str(UUID(int=2)),
    "starts_at": "2026-10-20T10:00:00Z",
    "ends_at": "2026-10-20T11:00:00Z",
    "status": "planned",
    "version": 1,
}


def call(owner, payload, status=200, failure=False):
    def transport(request):
        assert request.headers["Authorization"] == "Bearer token"
        assert request.extensions["timeout"]["read"] == 5.0
        assert request.url.path == (
            f"/internal/students/{UUID(int=1)}/current-class-period"
            if owner == "journal"
            else "/internal/lessons/lookup"
        )
        if failure:
            raise httpx.ConnectTimeout("secret", request=request)
        return httpx.Response(status, json=payload)

    async def run():
        async with httpx.AsyncClient(
            base_url="http://owner", transport=httpx.MockTransport(transport)
        ) as client:
            if owner == "journal":
                return await HttpJournalReader(client, "token").get_current_class_id(
                    UUID(int=1)
                )
            return await HttpScheduleReader(client, "token").get_lessons([22])

    return asyncio.run(run())


def test_readers_return_valid_class_and_batch():
    assert call("journal", PERIOD) == 7
    assert call("journal", {}, 404) is None
    assert call("schedule", [LESSON])[22].id == 22


@pytest.mark.parametrize(
    "change",
    [
        {"student_id": str(UUID(int=9))},
        {"left_at": "2026-10-01T10:00:00Z"},
        {"class_id": True},
        {"joined_at": "2026-09-01T10:00:00"},
        {"id": 0},
    ],
)
def test_bad_current_period_is_unavailable(change):
    with pytest.raises(OwnerLookupUnavailableError):
        call("journal", PERIOD | change)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [LESSON, LESSON],
        [LESSON | {"id": 23}],
        [LESSON | {"teacher_id": "bad"}],
        {},
        [LESSON | {"status": "unknown"}],
    ],
)
def test_bad_batch_is_unavailable(payload):
    with pytest.raises(OwnerLookupUnavailableError):
        call("schedule", payload)


@pytest.mark.parametrize("owner", ["journal", "schedule"])
@pytest.mark.parametrize("status", [401, 403, 302, 500])
def test_status_errors_are_not_absence(owner, status):
    with pytest.raises(OwnerLookupUnavailableError):
        call(owner, {}, status)


@pytest.mark.parametrize("owner", ["journal", "schedule"])
def test_network_error_is_unavailable(owner):
    with pytest.raises(OwnerLookupUnavailableError):
        call(owner, {}, failure=True)
