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


SCHOOL_PERIODS_PAYLOAD = {
    "timezone": "Asia/Yekaterinburg",
    "effective_from": "2026-11-30",
    "periods": [
        {"number": 1, "start_at": "09:00", "end_at": "09:45"},
        {"number": 2, "start_at": "09:55", "end_at": "10:40"},
        {"number": 3, "start_at": "11:00", "end_at": "11:45"},
        {"number": 4, "start_at": "11:55", "end_at": "12:40"},
        {"number": 5, "start_at": "13:00", "end_at": "13:45"},
        {"number": 6, "start_at": "13:55", "end_at": "14:40"},
        {"number": 7, "start_at": "15:00", "end_at": "15:45"},
    ],
}


def grid(**changes):
    payload = {
        "timezone": "Asia/Yekaterinburg",
        "effective_from": "2026-11-30",
        "periods": [dict(row) for row in SCHOOL_PERIODS_PAYLOAD["periods"]],
    }
    payload.update(changes)
    return payload


def call_periods(payload, status=200):
    from gateway_service.infrastructure.schedule_client import ScheduleClient

    def respond(request):
        assert request.headers["Authorization"] == "Bearer schedule-only"
        assert request.url.path == "/internal/school-periods"
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://schedule"
        ) as client:
            return await ScheduleClient(client, "schedule-only").get_school_periods()

    return asyncio.run(run())


def test_school_periods_match_internal_response_element_for_element():
    result = call_periods(SCHOOL_PERIODS_PAYLOAD)
    assert result.timezone == "Asia/Yekaterinburg"
    assert result.effective_from == date(2026, 11, 30)
    assert [row.model_dump() for row in result.periods] == (
        SCHOOL_PERIODS_PAYLOAD["periods"]
    )
    assert len(result.periods) == 7


@pytest.mark.parametrize(
    "payload",
    [
        {"secret": "bad"},
        {"timezone": "UTC", "effective_from": "2026-11-30", "periods": []},
        {"effective_from": "2026-11-30", "periods": []},
        {"timezone": "Asia/Yekaterinburg", "periods": []},
        {"timezone": "Asia/Yekaterinburg", "effective_from": "2026-11-30"},
        grid(effective_from="2026-13-01"),
        grid(effective_from="30-11-2026"),
        grid(periods="09:00"),
        grid(periods={"number": 1, "start_at": "09:00", "end_at": "09:45"}),
        grid(
            periods=[
                {"number": 0, "start_at": "09:00", "end_at": "09:45"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {"number": 8, "start_at": "09:00", "end_at": "09:45"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {"number": True, "start_at": "09:00", "end_at": "09:45"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {"number": 1, "start_at": "9:00", "end_at": "09:45"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {"number": 1, "start_at": "09:00", "end_at": "9:45"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {"number": 1, "start_at": "09:00:00", "end_at": "09:45:00"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {"number": 1, "start_at": "09:00", "end_at": "24:00"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                {
                    "number": 1,
                    "start_at": "09:00",
                    "end_at": "09:45",
                    "extra": "field",
                },
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
        grid(
            periods=[
                SCHOOL_PERIODS_PAYLOAD["periods"][0],
                SCHOOL_PERIODS_PAYLOAD["periods"][0],
                *SCHOOL_PERIODS_PAYLOAD["periods"][2:],
            ]
        ),
        grid(
            periods=[
                SCHOOL_PERIODS_PAYLOAD["periods"][1],
                SCHOOL_PERIODS_PAYLOAD["periods"][0],
                *SCHOOL_PERIODS_PAYLOAD["periods"][2:],
            ]
        ),
        grid(
            periods=[
                {"number": 1, "start_at": "09:45", "end_at": "09:00"},
                *SCHOOL_PERIODS_PAYLOAD["periods"][1:],
            ]
        ),
    ],
)
def test_corrupt_school_periods_is_unavailable(payload):
    from gateway_service.application.teacher_lessons import ScheduleUnavailableError

    with pytest.raises(ScheduleUnavailableError):
        call_periods(payload)


@pytest.mark.parametrize("status", [201, 301, 401, 403, 404, 422, 500])
def test_school_periods_internal_errors_are_unavailable(status):
    from gateway_service.application.teacher_lessons import ScheduleUnavailableError

    with pytest.raises(ScheduleUnavailableError):
        call_periods(SCHOOL_PERIODS_PAYLOAD, status)


def test_school_periods_network_failure_is_unavailable():
    from gateway_service.application.teacher_lessons import ScheduleUnavailableError

    with pytest.raises(ScheduleUnavailableError):
        call_periods(httpx.ConnectTimeout("secret"))
