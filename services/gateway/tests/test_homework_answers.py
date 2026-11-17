"""Контракт ответов не доверяет чужим ID и не раскрывает служебные поля."""

import asyncio
from uuid import UUID

import httpx
import pytest

from gateway_service.application.homework import HomeworkUnavailableError


def test_answer_client_passes_trusted_identity_and_validates_parent():
    from gateway_service.application.homework_answers import HomeworkAnswerInput
    from gateway_service.infrastructure.homework_answers_client import (
        HomeworkAnswersClient,
    )

    student = UUID(int=1)
    saved = {
        "id": 8,
        "homework_id": 7,
        "student_id": str(student),
        "attempt_number": 1,
        "answer_text": "Ответ",
        "status": "submitted",
        "submitted_at": "2026-10-20T12:00:00Z",
        "grade": None,
        "teacher_comment": "",
        "reviewer_id": None,
        "reviewed_at": None,
        "files": [],
    }

    async def run():
        def respond(request):
            assert request.headers["X-User-ID"] == str(student)
            assert request.headers["X-User-Role"] == "student"
            assert request.headers["Authorization"] == "Bearer internal"
            assert request.headers["Idempotency-Key"] == "stable-key"
            return httpx.Response(201, json=saved)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://homework"
        ) as http:
            client = HomeworkAnswersClient(http, "internal")
            answer, created = await client.submit(
                student, 7, "stable-key", HomeworkAnswerInput(answer_text="Ответ")
            )
            assert created and answer.id == 8
            saved["homework_id"] = 9
            with pytest.raises(HomeworkUnavailableError):
                await client.submit(
                    student, 7, "stable-key", HomeworkAnswerInput(answer_text="Ответ")
                )

    asyncio.run(run())


def test_answer_file_transport_uses_own_path_and_student_identity():
    from io import BytesIO

    from gateway_service.infrastructure.homework_file_client import HomeworkFileClient

    student = UUID(int=1)
    path = "/internal/homework/7/answers/8/files/9"

    async def respond(request):
        assert request.url.path == path
        assert request.headers["X-User-ID"] == str(student)
        assert request.headers["X-User-Role"] == "student"
        assert "X-Teacher-ID" not in request.headers
        if request.method == "PUT":
            assert b"answer" in await request.aread()
            return httpx.Response(
                200,
                json={
                    "id": 9,
                    "answer_id": 8,
                    "file_name": "answer.txt",
                    "size_bytes": 6,
                    "content_type": "text/plain",
                    "upload_status": "ready",
                },
            )
        return httpx.Response(
            200,
            content=b"answer",
            headers={
                "Content-Type": "text/plain",
                "Content-Length": "6",
                "Content-Disposition": "attachment; filename*=UTF-8''answer.txt",
            },
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://homework"
        ) as http:
            client = HomeworkFileClient(http, "internal")
            file = await client.upload_file(
                student_id=student,
                homework_id=7,
                answer_id=8,
                file_id=9,
                stream=BytesIO(b"answer"),
                file_name="answer.txt",
            )
            assert file.answer_id == 8
            async with client.download_file(
                user_id=student, role="student", homework_id=7, answer_id=8, file_id=9
            ) as (file, response):
                assert file.id == 9 and await response.aread() == b"answer"
            assert response.is_closed

    asyncio.run(run())
