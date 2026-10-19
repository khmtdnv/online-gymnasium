"""Проверяем реальные HTTP-клиенты на контролируемой транспортной границе."""

import asyncio
from uuid import UUID

import httpx
import pytest


def lesson_json(**changes):
    return {
        "id": 11,
        "class_id": 7,
        "subject_id": 3,
        "teacher_id": str(UUID(int=1)),
        "starts_at": "2026-11-01T10:00:00Z",
        "ends_at": "2026-11-01T11:00:00Z",
        "status": "planned",
        "version": 1,
        **changes,
    }


def run_schedule(*, status=200, payload=None, raw=None, error=False, path="get_lesson"):
    from homework_service.infrastructure.schedule_client import HttpScheduleReader

    async def run():
        def transport(request):
            assert request.headers["Authorization"] == "Bearer schedule-only"
            assert request.extensions["timeout"]["read"] == 5.0
            if error:
                raise httpx.ConnectError("private network detail", request=request)
            return (
                httpx.Response(status, content=raw)
                if raw is not None
                else httpx.Response(status, json=payload)
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), base_url="http://schedule"
        ) as client:
            return await getattr(HttpScheduleReader(client, "schedule-only"), path)(11)

    return asyncio.run(run())


def test_get_lesson_and_confirmed_absence():
    assert run_schedule(payload=lesson_json()).teacher_id == UUID(int=1)
    assert run_schedule(status=404) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 12},
        {"id": True},
        {"class_id": "7"},
        {"teacher_id": "bad"},
        {"status": "unknown"},
        {"version": 0},
        {"starts_at": "2026-11-01T10:00:00"},
        {"ends_at": "2026-11-01T09:00:00Z"},
    ],
)
def test_schedule_contract_failure(changes):
    from homework_service.application.ports.errors import OwnerLookupUnavailableError

    with pytest.raises(OwnerLookupUnavailableError):
        run_schedule(payload=lesson_json(**changes))


@pytest.mark.parametrize("status", [201, 204, 301, 302, 401, 403, 422, 500, 503])
def test_unexpected_status_is_availability_error(status):
    from homework_service.application.ports.errors import OwnerLookupUnavailableError

    with pytest.raises(OwnerLookupUnavailableError):
        run_schedule(status=status, payload=lesson_json())


@pytest.mark.parametrize(
    "options",
    [{"raw": b"not json"}, {"payload": {}}, {"error": True}, {"payload": None}],
)
def test_malformed_or_network_failure(options):
    from homework_service.application.ports.errors import OwnerLookupUnavailableError

    with pytest.raises(OwnerLookupUnavailableError):
        run_schedule(**options)


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, None, None),
        (
            200,
            lesson_json(
                id=12, starts_at="2026-11-02T10:00:00Z", ends_at="2026-11-02T11:00:00Z"
            ),
            12,
        ),
        (404, None, "error"),
        (503, None, "error"),
        (200, lesson_json(id=12, class_id=8), "error"),
        (200, lesson_json(id=12, subject_id=4), "error"),
        (200, lesson_json(id=12, status="canceled"), "error"),
        (200, lesson_json(id=11), "error"),
        (200, lesson_json(id=12), "error"),
    ],
)
def test_next_candidate_is_checked_against_source(status, payload, expected):
    from homework_service.application.ports.errors import OwnerLookupUnavailableError
    from homework_service.infrastructure.schedule_client import HttpScheduleReader

    async def run():
        def transport(request):
            if request.url.path.endswith("/next"):
                return (
                    httpx.Response(status, content=b"null")
                    if payload is None
                    else httpx.Response(status, json=payload)
                )
            return httpx.Response(200, json=lesson_json())

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), base_url="http://schedule"
        ) as client:
            return await HttpScheduleReader(client, "schedule-only").get_next_lesson(11)

    if expected == "error":
        with pytest.raises(OwnerLookupUnavailableError):
            asyncio.run(run())
    else:
        result = asyncio.run(run())
        assert (None if result is None else result.id) == expected


@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"teacher_id": str(UUID(int=1)), "class_id": 7}, True),
        (404, None, False),
        (200, {"teacher_id": str(UUID(int=2)), "class_id": 7}, "error"),
        (200, {"teacher_id": str(UUID(int=1)), "class_id": 8}, "error"),
        (200, {}, "error"),
        (200, {"teacher_id": str(UUID(int=1)), "class_id": "7"}, "error"),
        (204, None, "error"),
        (302, None, "error"),
        (401, None, "error"),
        (403, None, "error"),
        (500, None, "error"),
    ],
)
def test_journal_exact_pair(status, payload, expected):
    from homework_service.application.ports.errors import OwnerLookupUnavailableError
    from homework_service.infrastructure.journal_client import HttpJournalReader

    async def run():
        def transport(request):
            assert request.headers["Authorization"] == "Bearer journal-only"
            assert request.url.path == f"/internal/teachers/{UUID(int=1)}/classes/7"
            return httpx.Response(status, json=payload)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), base_url="http://journal"
        ) as client:
            return await HttpJournalReader(client, "journal-only").is_teacher_assigned(
                UUID(int=1), 7
            )

    if expected == "error":
        with pytest.raises(OwnerLookupUnavailableError):
            asyncio.run(run())
    else:
        assert asyncio.run(run()) is expected


@pytest.mark.parametrize("kind", ["timeout", "bad_json"])
def test_journal_failure_does_not_mean_no_assignment(kind):
    from homework_service.application.ports.errors import OwnerLookupUnavailableError
    from homework_service.infrastructure.journal_client import HttpJournalReader

    async def run():
        def transport(request):
            if kind == "timeout":
                raise httpx.ReadTimeout("secret", request=request)
            return httpx.Response(200, content=b"not JSON")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), base_url="http://journal"
        ) as client:
            return await HttpJournalReader(client, "journal-only").is_teacher_assigned(
                UUID(int=1), 7
            )

    with pytest.raises(OwnerLookupUnavailableError):
        asyncio.run(run())
