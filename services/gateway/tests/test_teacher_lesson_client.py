"""Gateway принимает только согласованную карточку запрошенного урока."""

import asyncio
from copy import deepcopy
from uuid import UUID

import httpx
import pytest
from test_schedule_client import lesson

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.infrastructure.homework_client import HomeworkClient


def card():
    return {
        "lesson": lesson(),
        "next_lesson": None,
        "homework_for_lesson": [],
        "homework_from_lesson": [],
    }


def call(payload, status=200):
    def respond(request):
        assert request.url.path == "/internal/teacher-lessons/11"
        assert request.headers["X-Teacher-ID"] == str(UUID(int=1))
        assert request.headers["Authorization"] == "Bearer homework-only"
        return httpx.Response(status, json=payload)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://homework"
        ) as client:
            return await HomeworkClient(client, "homework-only").get_teacher_lesson(
                teacher_id=UUID(int=1), lesson_id=11
            )

    return asyncio.run(run())


def test_card_and_next_with_another_teacher():
    payload = card()
    payload["next_lesson"] = lesson(
        12,
        teacher_id=str(UUID(int=2)),
        starts_at="2026-10-20T10:00:00Z",
        ends_at="2026-10-20T11:00:00Z",
    )
    assert call(payload).next_lesson.id == 12


@pytest.mark.parametrize(
    "change",
    [
        {"id": 12},
        {"teacher_id": str(UUID(int=2))},
        {"status": "unknown"},
    ],
)
def test_bad_lesson_identity_rejected(change):
    payload = card()
    payload["lesson"].update(change)
    with pytest.raises(HomeworkUnavailableError):
        call(payload)


@pytest.mark.parametrize(
    "next_lesson", [lesson(12), lesson(12, class_id=8), lesson(12, status="canceled")]
)
def test_bad_next_rejected(next_lesson):
    payload = deepcopy(card())
    payload["next_lesson"] = next_lesson
    with pytest.raises(HomeworkUnavailableError):
        call(payload)


@pytest.mark.parametrize(
    "code,status", [("access_denied", 403), ("lesson_not_found", 404)]
)
def test_known_business_error(code, status):
    with pytest.raises(HomeworkRequestError) as error:
        call({"error": {"code": code}}, status)
    assert error.value.status_code == status


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
def test_unknown_or_service_errors_are_unavailable(status):
    with pytest.raises(HomeworkUnavailableError):
        call({"error": {"code": "invalid_service_credentials"}}, status)


def homework(**changes):
    return {
        "id": 1,
        "issued_lesson_id": 11,
        "class_id": 7,
        "subject_id": 3,
        "author_id": str(UUID(int=1)),
        "description": "Задача",
        "due_lesson_id": None,
        "manual_due_datetime": "2026-10-20T10:00:00Z",
        "created_at": "2026-10-19T09:00:00Z",
        "final_due_datetime": "2026-10-20T10:00:00Z",
        "due_status": "manual",
    } | changes


@pytest.mark.parametrize(
    "change",
    [
        {"class_id": 8},
        {"subject_id": 4},
        {"issued_lesson_id": 99},
        {"due_status": "fixed"},
        {"final_due_datetime": None},
    ],
)
def test_incompatible_homework_in_card_rejected(change):
    payload = card()
    payload["homework_from_lesson"] = [homework(**change)]
    with pytest.raises(HomeworkUnavailableError):
        call(payload)


def test_duplicate_and_wrong_due_group_rejected():
    payload = card()
    payload["homework_from_lesson"] = [homework(), homework(id=2)]
    with pytest.raises(HomeworkUnavailableError):
        call(payload)
    payload["homework_from_lesson"] = []
    payload["homework_for_lesson"] = [homework()]
    with pytest.raises(HomeworkUnavailableError):
        call(payload)


def test_manual_assignment_is_accepted_without_link_to_another_lesson():
    payload = card()
    payload["homework_from_lesson"] = [homework()]
    result = call(payload)
    assert result.homework_from_lesson[0].due_status == "manual"
    assert result.homework_for_lesson == []


@pytest.mark.parametrize(
    "source_status,due_status,deadline",
    [
        ("planned", "lesson_cancelled", None),
        ("planned", "lesson", "2026-10-20T10:00:00Z"),
        ("canceled", "lesson", "2026-10-19T10:00:00Z"),
    ],
)
def test_due_homework_matches_included_lesson_snapshot(
    source_status, due_status, deadline
):
    payload = card()
    payload["lesson"]["status"] = source_status
    payload["homework_for_lesson"] = [
        homework(
            issued_lesson_id=10,
            due_lesson_id=11,
            manual_due_datetime=None,
            due_status=due_status,
            final_due_datetime=deadline,
        )
    ]
    with pytest.raises(HomeworkUnavailableError):
        call(payload)
