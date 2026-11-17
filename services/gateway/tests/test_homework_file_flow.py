"""Настоящие ручки и клиент: неизвестный исход PUT, повтор и отзыв прав."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
from test_homework_api import TEACHER, make_app

from gateway_service.infrastructure.homework_file_client import HomeworkFileClient


def test_gateway_upload_retries_same_file_after_lost_response_and_rechecks_rights(
    monkeypatch,
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "homework" / "src")
    )
    from homework_service.app import create_app
    from homework_service.application.file_access import check_teacher_access
    from homework_service.application.homework_files import (
        HomeworkFileResult,
        UploadHomeworkFileHandler,
    )
    from homework_service.application.ports.schedule_reader import LessonInfo
    from homework_service.config import HomeworkSettings
    from homework_service.domain.homework import Homework
    from homework_service.domain.homework_file import HomeworkFile

    parent = Homework(
        id=1,
        issued_lesson_id=11,
        due_lesson_id=12,
        class_id=7,
        subject_id=3,
        author_id=TEACHER,
        description="Задание",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    file = HomeworkFile(
        id=8,
        homework_id=1,
        file_name="Задачи.txt",
        size_bytes=6,
        content_type="text/plain",
        content_sha256="a" * 64,
    )
    state = {"assigned": True, "lost": True, "writes": 0, "uow": False}

    @asynccontextmanager
    async def uow():
        state["uow"] = True
        try:
            yield SimpleNamespace(
                homeworks=SimpleNamespace(get_by_id=AsyncMock(return_value=parent)),
                files=SimpleNamespace(get_by_id=AsyncMock(return_value=file)),
            )
        finally:
            state["uow"] = False

    async def lesson(lesson_id):
        assert not state["uow"]
        return LessonInfo(
            id=11,
            teacher_id=TEACHER,
            class_id=7,
            subject_id=3,
            starts_at=datetime(2026, 10, 20, 10, tzinfo=UTC),
            ends_at=datetime(2026, 10, 20, 11, tzinfo=UTC),
            status="planned",
            version=1,
        )

    async def assigned(teacher_id, class_id):
        assert not state["uow"] and teacher_id == TEACHER and class_id == 7
        return state["assigned"]

    async def check(teacher_id, homework):
        await check_teacher_access(
            teacher_id,
            homework,
            SimpleNamespace(get_lesson=lesson),
            SimpleNamespace(is_teacher_assigned=assigned),
        )

    async def save(file, stream):
        assert not state["uow"] and stream.read() == b"answer"
        state["writes"] += 1
        return "homework/private", datetime.now(UTC)

    async def finish(file, key, started):
        file.upload_status = "ready"
        file.storage_key = key
        return HomeworkFileResult.from_file(file)

    owner = create_app(
        HomeworkSettings(
            database_url="unused", gateway_service_token="gw", _env_file=None
        ),
        AsyncMock(),
        upload_homework_file_handler=UploadHomeworkFileHandler(
            uow, check, save, finish
        ),
    )
    owner_transport = httpx.ASGITransport(app=owner)

    async def forwarding(request):
        assert request.headers["X-Teacher-ID"] == str(TEACHER)
        response = await owner_transport.handle_async_request(request)
        if state["lost"]:
            state["lost"] = False
            await response.aclose()
            raise httpx.ReadTimeout("response lost after committing")
        return response

    async def run():
        async with (
            owner.router.lifespan_context(owner),
            httpx.AsyncClient(
                base_url="http://homework", transport=httpx.MockTransport(forwarding)
            ) as internal,
        ):
            gateway, token, _ = make_app()
            client = HomeworkFileClient(internal, "gw")
            gateway.state.homework_file_client = client
            gateway.state.injected_homework_file_client = client
            async with (
                gateway.router.lifespan_context(gateway),
                httpx.AsyncClient(
                    base_url="http://gateway",
                    transport=httpx.ASGITransport(app=gateway),
                ) as public,
            ):
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-Teacher-ID": str(UUID(int=99)),
                }
                path = "/api/v1/homework/1/files/8"

                async def upload():
                    return await public.put(
                        path, headers=headers, files={"file": ("Задачи.txt", b"answer")}
                    )

                first = await upload()
                assert first.status_code == 503, first.text
                assert file.upload_status == "ready" and state["writes"] == 1
                second = await upload()
                assert second.status_code == 200, second.text
                assert second.json()["id"] == 8 and state["writes"] == 1
                state["assigned"] = False
                denied = await upload()
                assert denied.status_code == 403 and state["writes"] == 1

    asyncio.run(run())
