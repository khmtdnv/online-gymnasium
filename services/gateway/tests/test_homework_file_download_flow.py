"""Реальные API/handlers/client двух сервисов, с заменой только БД/MinIO/владельцев."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from test_homework_api import TEACHER, make_app

from gateway_service.domain.user import Role
from gateway_service.infrastructure.homework_file_client import HomeworkFileClient


@pytest.mark.parametrize(
    "role,own_due", [(Role.STUDENT, False), (Role.TEACHER, False), (Role.TEACHER, True)]
)
def test_download_rechecks_rights_and_ready_state_through_gateway_and_homework(
    monkeypatch, role, own_due
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "homework" / "src")
    )
    import homework_service.app as module
    from homework_service.application.homework_files import GetHomeworkFileHandler
    from homework_service.application.ports.schedule_reader import LessonInfo
    from homework_service.config import HomeworkSettings
    from homework_service.domain.homework import Homework
    from homework_service.domain.homework_file import HomeworkFile

    state = {"class_id": 7, "assigned": True, "ready": True, "missing": False}
    streams = []
    parent = Homework(
        id=1,
        issued_lesson_id=11,
        due_lesson_id=22,
        class_id=7,
        subject_id=3,
        author_id=TEACHER,
        description="Решить задачу",
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )

    async def get_homework(id):
        return parent

    async def get_file(id):
        return HomeworkFile(
            id=8,
            homework_id=1,
            file_name="Ответ.txt",
            size_bytes=6,
            content_type="text/plain",
            content_sha256="a" * 64,
            upload_status="ready" if state["ready"] else "pending",
            storage_key="homework/private" if state["ready"] else None,
        )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            homeworks=SimpleNamespace(get_by_id=get_homework),
            files=SimpleNamespace(get_by_id=get_file),
        )

    async def current(user_id):
        assert user_id == TEACHER
        return state["class_id"]

    async def assigned(user_id, class_id):
        return state["assigned"]

    async def lessons(ids):
        return {
            id: LessonInfo(
                id=id,
                class_id=7,
                subject_id=3,
                teacher_id=TEACHER if (id == 22) == own_due else UUID(int=3),
                starts_at=datetime(2026, 10, 20, 10, tzinfo=UTC),
                ends_at=datetime(2026, 10, 20, 11, tzinfo=UTC),
                status="planned",
                version=1,
            )
            for id in ids
        }

    class Storage:
        @contextmanager
        def open(self, key):
            assert key == "homework/private"
            if state["missing"]:
                raise OSError("secret")
            with BytesIO(b"answer") as stream:
                streams.append(stream)
                yield stream

        def close(self):
            pass

    monkeypatch.setattr(module, "create_file_storage", lambda settings: Storage())
    owner = module.create_app(
        HomeworkSettings(
            database_url="unused", gateway_service_token="gw", _env_file=None
        ),
        AsyncMock(),
        get_homework_file_handler=GetHomeworkFileHandler(
            uow,
            SimpleNamespace(get_current_class_id=current, is_teacher_assigned=assigned),
            SimpleNamespace(get_lessons=lessons),
        ),
    )

    async def run():
        async with (
            owner.router.lifespan_context(owner),
            httpx.AsyncClient(
                base_url="http://homework", transport=httpx.ASGITransport(app=owner)
            ) as internal,
        ):
            gateway, token, _ = make_app(role=role)
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
                path = "/api/v1/homework/1/files/8"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-User-Role": "admin",
                    "X-User-ID": str(UUID(int=999)),
                }
                response = await public.get(path, headers=headers)
                assert response.status_code == 200 and response.content == b"answer", (
                    response.text
                )
                head = await public.head(path, headers=headers)
                assert (
                    head.status_code == 200
                    and head.content == b""
                    and head.headers["content-length"] == "6"
                )
                state["ready"] = False
                assert (await public.get(path, headers=headers)).status_code == 409
                state["ready"] = True
                state["missing"] = True
                response = await public.get(path, headers=headers)
                assert response.status_code == 503 and "secret" not in response.text
                state["missing"] = False
                state["class_id"] = 8
                state["assigned"] = False
                for method in ("GET", "HEAD"):
                    response = await public.request(method, path, headers=headers)
                    assert response.status_code == (
                        404 if role == Role.STUDENT else 403
                    )

    asyncio.run(run())
    assert streams and all(stream.closed for stream in streams)
