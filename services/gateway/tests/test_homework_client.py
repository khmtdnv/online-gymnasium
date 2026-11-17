"""Gateway не доверяет статусу или JSON другого сервиса без проверки."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

TEACHER = UUID("75ef34f4-2588-41b1-b41e-cbd058c6025c")
SAVED = {
    "id": 1,
    "issued_lesson_id": 11,
    "class_id": 7,
    "subject_id": 3,
    "author_id": str(TEACHER),
    "description": "Решить задачу",
    "due_lesson_id": 12,
    "manual_due_datetime": None,
    "created_at": "2026-10-17T10:00:00Z",
}


def call_client(respond, *, due=None, files=None):
    from gateway_service.infrastructure.homework_client import HomeworkClient

    async def run():
        async with httpx.AsyncClient(
            base_url="http://homework",
            transport=httpx.MockTransport(respond),
        ) as http_client:
            client = HomeworkClient(http_client, "service-test")
            return await client.create_homework(
                teacher_id=TEACHER,
                issued_lesson_id=11,
                description="Решить задачу",
                due_lesson_id=12 if due is None else None,
                manual_due_datetime=due,
                **({"files": files} if files is not None else {}),
            )

    return asyncio.run(run())


def expected_file(**changes):
    return {
        "file_name": "Задачи.pdf",
        "size_bytes": 1024,
        "content_type": "application/pdf",
        "content_sha256": "a" * 64,
    } | changes


def saved_file(**changes):
    return {
        "id": 8,
        "homework_id": 1,
        "file_name": "Задачи.pdf",
        "size_bytes": 1024,
        "content_type": "application/pdf",
        "upload_status": "pending",
    } | changes


def test_client_forwards_expected_files_and_checks_reserved_result():
    def respond(request):
        assert json.loads(request.content)["files"] == [expected_file()]
        return httpx.Response(201, json={**SAVED, "files": [saved_file()]})

    result = call_client(respond, files=[expected_file()])
    assert result.files[0].id == 8
    assert result.files[0].upload_status == "pending"


@pytest.mark.parametrize(
    "files",
    [
        [],
        [saved_file(homework_id=999)],
        [saved_file(size_bytes=1)],
        [saved_file(file_name="Другое.pdf")],
        [saved_file(upload_status="ready")],
        [saved_file(id=True)],
        [saved_file(storage_key="private")],
    ],
)
def test_reserved_file_response_must_match_request(files):
    from gateway_service.application.homework import HomeworkUnavailableError

    with pytest.raises(HomeworkUnavailableError):
        call_client(
            lambda request: httpx.Response(201, json={**SAVED, "files": files}),
            files=[expected_file()],
        )


def test_gateway_input_rejects_unsafe_file_metadata():
    from pydantic import ValidationError

    from gateway_service.application.homework import CreateHomeworkRequest

    with pytest.raises(ValidationError):
        CreateHomeworkRequest(
            description="Решить",
            due_lesson_id=12,
            files=[expected_file(file_name="../x.pdf")],
        )


@pytest.mark.parametrize("due", [None, datetime(2026, 10, 20, tzinfo=UTC)])
def test_client_sends_only_trusted_headers_and_checks_success(due):
    def respond(request):
        assert str(request.url) == "http://homework/internal/lessons/11/homework"
        assert request.headers["authorization"] == "Bearer service-test"
        assert request.headers["x-teacher-id"] == str(TEACHER)
        body = json.loads(request.content)
        assert body["description"] == "Решить задачу"
        assert "teacher_id" not in body
        if due:
            assert body["due_lesson_id"] is None
            assert datetime.fromisoformat(body["manual_due_datetime"]) == due
        else:
            assert body["due_lesson_id"] == 12 and body["manual_due_datetime"] is None
        saved = (
            {**SAVED, "due_lesson_id": None, "manual_due_datetime": due.isoformat()}
            if due
            else SAVED
        )
        return httpx.Response(201, json=saved)

    assert call_client(respond, due=due).id == 1


@pytest.mark.parametrize(
    "change",
    [
        {"author_id": "75ef34f4-2588-41b1-b41e-cbd058c6025d"},
        {"issued_lesson_id": 99},
        {"description": "другое"},
        {"due_lesson_id": 99},
        {"manual_due_datetime": "2026-10-20T10:00:00Z"},
        {"id": True},
        {"created_at": "yesterday"},
    ],
)
def test_wrong_success_contract_is_unavailable(change):
    from gateway_service.application.homework import HomeworkUnavailableError

    with pytest.raises(HomeworkUnavailableError):
        call_client(lambda request: httpx.Response(201, json={**SAVED, **change}))


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (403, "access_denied"),
        (404, "lesson_not_found"),
        (409, "homework_already_exists"),
        (422, "invalid_homework_data"),
    ],
)
def test_only_known_business_errors_are_propagated(status, code):
    from gateway_service.application.homework import HomeworkRequestError

    with pytest.raises(HomeworkRequestError) as caught:
        call_client(
            lambda request: httpx.Response(
                status,
                json={
                    "error": {"code": code, "message": "unsafe owner text"},
                },
            )
        )
    assert caught.value.status_code == status
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (200, SAVED),
        (302, SAVED),
        (500, {}),
        (401, {"error": {"code": "invalid_service_credentials"}}),
        (403, {"error": {"code": "invalid_service_credentials"}}),
        (409, {"error": {"code": "unknown"}}),
        (404, {"detail": "secret"}),
        (201, []),
        (201, None),
    ],
)
def test_unknown_responses_do_not_become_user_errors(status, payload):
    from gateway_service.application.homework import HomeworkUnavailableError

    with pytest.raises(HomeworkUnavailableError):
        call_client(lambda request: httpx.Response(status, json=payload))


def test_timeout_does_not_retry_post():
    from gateway_service.application.homework import HomeworkUnavailableError

    calls = []

    def respond(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] == 5.0
        raise httpx.ReadTimeout("secret", request=request)

    with pytest.raises(HomeworkUnavailableError):
        call_client(respond)
    assert len(calls) == 1


def test_invalid_json_is_unavailable():
    from gateway_service.application.homework import HomeworkUnavailableError

    with pytest.raises(HomeworkUnavailableError):
        call_client(lambda request: httpx.Response(201, content=b"not-json"))
