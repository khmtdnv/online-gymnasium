"""Gateway проверяет не только JSON заданий, но и границы страницы/сроки."""

import asyncio
from uuid import UUID

import httpx
import pytest

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.infrastructure.homework_client import HomeworkClient

ROW = {
    "id": 1,
    "issued_lesson_id": 11,
    "class_id": 7,
    "subject_id": 3,
    "author_id": str(UUID(int=2)),
    "description": "Задача",
    "due_lesson_id": None,
    "manual_due_datetime": "2026-10-20T10:00:00Z",
    "created_at": "2026-10-01T10:00:00Z",
    "final_due_datetime": "2026-10-20T10:00:00Z",
    "due_status": "manual",
}


def call(payload, status=200, *, many=True, limit=2, failure=False):
    def respond(request):
        assert request.headers["Authorization"] == "Bearer service"
        assert request.headers["X-Student-ID"] == str(UUID(int=1))
        assert request.method == "GET"
        assert request.url.path == (
            "/internal/homework" if many else "/internal/homework/1"
        )
        if many:
            assert dict(request.url.params) == {"limit": str(limit), "offset": "0"}
        if failure:
            raise httpx.ReadTimeout("secret", request=request)
        return httpx.Response(status, json=payload)

    async def run():
        async with httpx.AsyncClient(
            base_url="http://homework", transport=httpx.MockTransport(respond)
        ) as http:
            client = HomeworkClient(http, "service")
            if many:
                return await client.list_student_homework(
                    student_id=UUID(int=1), limit=limit, offset=0
                )
            return await client.get_student_homework(
                student_id=UUID(int=1), homework_id=1
            )

    return asyncio.run(run())


def test_valid_page_and_one_response():
    assert [item.id for item in call([ROW])] == [1]
    assert call(ROW, many=False).due_status == "manual"
    assert call([]) == []


@pytest.mark.parametrize(
    "payload",
    [
        [ROW, ROW],
        [ROW, ROW | {"id": 2, "class_id": 8}],
        [ROW, ROW | {"id": 2}],
        [ROW | {"due_status": "lesson"}],
        [ROW | {"due_status": "fixed"}],
        [ROW | {"final_due_datetime": None}],
        [ROW | {"due_lesson_id": 22}],
        [ROW | {"description": "  Задача  "}],
        [
            ROW
            | {
                "manual_due_datetime": None,
                "due_lesson_id": 22,
                "due_status": "lesson_cancelled",
            }
        ],
        {},
        [ROW | {"id": True}],
    ],
)
def test_bad_page_is_unavailable(payload):
    with pytest.raises(HomeworkUnavailableError):
        call(payload)


def test_overfull_page_is_unavailable():
    with pytest.raises(HomeworkUnavailableError):
        call([ROW | {"id": 2}, ROW], limit=1)


def test_wrong_single_id_is_unavailable():
    with pytest.raises(HomeworkUnavailableError):
        call(ROW | {"id": 2}, many=False)


@pytest.mark.parametrize("status", [401, 403, 302, 500])
def test_service_failures_do_not_become_user_authentication_errors(status):
    with pytest.raises(HomeworkUnavailableError):
        call({"error": {"code": "invalid_service_credentials"}}, status)


def test_only_known_read_not_found_is_forwarded():
    with pytest.raises(HomeworkRequestError) as caught:
        call({"error": {"code": "homework_not_found"}}, 404, many=False)
    assert caught.value.status_code == 404
    with pytest.raises(HomeworkUnavailableError):
        call({"error": {"code": "lesson_not_found"}}, 404, many=False)
    with pytest.raises(HomeworkUnavailableError):
        call({"error": {"code": "homework_not_found"}}, 404)


def test_network_failure_is_unavailable():
    with pytest.raises(HomeworkUnavailableError):
        call({}, failure=True)
