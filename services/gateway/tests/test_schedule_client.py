"""Gateway проверяет владельца, диапазон и порядок расписания."""

import asyncio
from datetime import date
from uuid import UUID

import httpx
import pytest


def lesson(id=11, **changes):
    return {
        "id": id,
        "class_id": 7,
        "teacher_id": str(UUID(int=1)),
        "subject_id": 3,
        "starts_at": "2026-10-19T10:00:00Z",
        "ends_at": "2026-10-19T11:00:00Z",
        "status": "planned",
        "version": 1,
    } | changes


def call(payload, status=200):
    from gateway_service.infrastructure.schedule_client import ScheduleClient

    def respond(request):
        assert request.headers["Authorization"] == "Bearer schedule-only"
        assert request.headers["X-Teacher-ID"] == str(UUID(int=1))
        assert request.url.path == "/internal/teacher-lessons"
        assert request.url.params["date_from"] == "2026-10-19"
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://schedule"
        ) as client:
            return await ScheduleClient(client, "schedule-only").list_teacher_lessons(
                teacher_id=UUID(int=1),
                date_from=date(2026, 10, 19),
                date_to=date(2026, 10, 25),
            )

    return asyncio.run(run())


def test_list_accepts_empty_cancelled_and_overlapping_boundary():
    assert call([]) == []
    assert call([lesson(status="canceled")])[0].status == "canceled"
    assert (
        call(
            [lesson(starts_at="2026-10-18T23:30:00Z", ends_at="2026-10-19T00:30:00Z")]
        )[0].id
        == 11
    )


@pytest.mark.parametrize(
    "payload",
    [
        [lesson(teacher_id=str(UUID(int=2)))],
        [lesson(), lesson()],
        [lesson(12), lesson(11)],
        [lesson(starts_at="2026-10-26T00:00:00Z", ends_at="2026-10-26T01:00:00Z")],
        [lesson(starts_at="2026-10-18T23:00:00Z", ends_at="2026-10-19T00:00:00Z")],
        [lesson(status="unknown")],
        [lesson(id=True)],
        {"secret": "bad"},
    ],
)
def test_invalid_response_is_unavailable(payload):
    from gateway_service.application.teacher_lessons import ScheduleUnavailableError

    with pytest.raises(ScheduleUnavailableError):
        call(payload)


@pytest.mark.parametrize("status", [201, 301, 401, 403, 404, 422, 500])
def test_internal_errors_do_not_become_user_auth_errors(status):
    from gateway_service.application.teacher_lessons import ScheduleUnavailableError

    with pytest.raises(ScheduleUnavailableError):
        call({"detail": "secret"}, status)


def test_network_failure_is_unavailable():
    from gateway_service.application.teacher_lessons import ScheduleUnavailableError

    with pytest.raises(ScheduleUnavailableError):
        call(httpx.ConnectTimeout("secret"))
