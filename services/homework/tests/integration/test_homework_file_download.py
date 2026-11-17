"""Настоящие PostgreSQL и MinIO: ученический upload handler → закрытое скачивание."""

import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from homework_service.app import create_app
from homework_service.application.homework_files import (
    GetHomeworkFileHandler,
    HomeworkFileInput,
    UploadHomeworkFileHandler,
)
from homework_service.application.ports.schedule_reader import LessonInfo
from homework_service.domain.homework import Homework
from homework_service.infrastructure.file_upload import finish_upload, save_file
from homework_service.infrastructure.minio_file_storage import create_file_storage
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_domain_homework import data

pytestmark = pytest.mark.integration


def test_real_uploaded_file_is_downloaded_with_exact_bytes_and_safe_headers(
    engine, minio_settings
):
    content = "Решение задания".encode()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = create_file_storage(minio_settings)
    keys = []
    teacher = UUID(int=2)

    def uow_factory():
        return SqlAlchemyUnitOfWork(factory)

    async def current(user_id):
        return 7

    async def assigned(user_id, class_id):
        return True

    async def lessons(ids):
        return {
            id: LessonInfo(
                id=id,
                class_id=7,
                subject_id=3,
                teacher_id=teacher,
                starts_at=datetime(2026, 10, 20, 10, tzinfo=UTC),
                ends_at=datetime(2026, 10, 20, 11, tzinfo=UTC),
                status="planned",
                version=1,
            )
            for id in ids
        }

    async def prepare():
        async with uow_factory() as uow:
            homework = await uow.homeworks.add(
                Homework(
                    **data(
                        author_id=teacher,
                        due_lesson_id=None,
                        manual_due_datetime=datetime(2030, 1, 1, tzinfo=UTC),
                    )
                )
            )
            files = await uow.files.add_files(
                homework.id,
                [
                    HomeworkFileInput(
                        file_name="Ответ.txt",
                        size_bytes=len(content),
                        content_type="text/plain",
                        content_sha256=hashlib.sha256(content).hexdigest(),
                    )
                ],
            )

        async def check_teacher_access(user_id, parent):
            assert user_id == teacher and parent.author_id == teacher

        async def save(file, stream):
            key, started = await save_file(file, stream, uow_factory, storage)
            keys.append(key)
            return key, started

        async def finish(file, key, started):
            return await finish_upload(file, key, started, uow_factory, storage)

        handler = UploadHomeworkFileHandler(
            uow_factory, check_teacher_access, save, finish
        )
        return homework.id, files[0].id, handler

    try:
        homework_id, file_id, upload_handler = asyncio.run(prepare())
        settings = minio_settings.model_copy(
            update={"gateway_service_token": "test-gateway"}
        )
        handler = GetHomeworkFileHandler(
            uow_factory,
            SimpleNamespace(get_current_class_id=current, is_teacher_assigned=assigned),
            SimpleNamespace(get_lessons=lessons),
        )
        app = create_app(
            settings,
            engine,
            get_homework_file_handler=handler,
            upload_homework_file_handler=upload_handler,
        )
        with TestClient(app) as client:
            path = f"/internal/homework/{homework_id}/files/{file_id}"
            headers = {
                "Authorization": "Bearer test-gateway",
                "X-User-ID": str(UUID(int=1)),
                "X-User-Role": "student",
            }
            upload_headers = {
                "Authorization": "Bearer test-gateway",
                "X-Teacher-ID": str(teacher),
            }
            for _ in range(2):
                response = client.put(
                    path, headers=upload_headers, files={"file": ("Ответ.txt", content)}
                )
                assert response.status_code == 200, response.text
                assert response.json()["upload_status"] == "ready"
            assert len(keys) == 1
            response = client.get(path, headers=headers)
            assert response.status_code == 200 and response.content == content
            assert response.headers["content-length"] == str(len(content))
            assert response.headers["content-type"] == "text/plain"
            assert response.headers["cache-control"] == "private, no-store"
            assert "storage_key" not in response.text
            head = client.head(path, headers=headers)
            assert head.status_code == 200 and head.content == b""
            assert head.headers["content-length"] == str(len(content))
    finally:
        for key in keys:
            storage.delete(key)
        storage.close()
