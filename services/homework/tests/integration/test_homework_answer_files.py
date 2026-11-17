"""Ключевой цикл файла: готовность, возврат и запрет позднего изменения работы."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Event
from uuid import UUID

import pytest

from homework_service.application.homework_answer_files import (
    HomeworkAnswerFilesHandler,
)
from homework_service.application.homework_answers import (
    ReviewHomeworkAnswerCommand,
    SubmitHomeworkAnswerCommand,
)
from homework_service.application.homework_files import HomeworkFileInput
from homework_service.application.ports.errors import (
    HomeworkAnswerConflictError,
    HomeworkAnswerNotFoundError,
)
from homework_service.cleanup_files import cleanup_files
from homework_service.domain.homework import Homework
from homework_service.infrastructure.minio_file_storage import create_file_storage
from tests.integration.test_homework_answers import STUDENT, TEACHER, handlers
from tests.test_domain_homework import data

pytestmark = pytest.mark.integration


def test_answer_file_ready_review_and_ownership(engine, minio_settings, monkeypatch):
    uow, submit, review = handlers(engine)
    storage = create_file_storage(minio_settings)
    files = HomeworkAnswerFilesHandler(
        uow, submit._journal_reader, submit._schedule_reader, storage
    )
    keys = []

    async def run():
        async with uow() as unit:
            parent = await unit.homeworks.add(Homework(**data(author_id=TEACHER)))
        metadata = HomeworkFileInput(
            file_name="Решение.txt",
            size_bytes=6,
            content_type="text/plain",
            content_sha256=hashlib.sha256(b"answer").hexdigest(),
        )
        result = await submit.handle(
            SubmitHomeworkAnswerCommand(
                student_id=STUDENT,
                homework_id=parent.id,
                idempotency_key="file",
                files=[metadata],
            )
        )
        answer = result.answer
        file_id = answer.files[0].id

        async def download(student_id):
            return await files.get_file(
                student_id, "student", parent.id, answer.id, file_id
            )

        with pytest.raises(HomeworkAnswerNotFoundError):
            await download(UUID(int=99))
        with pytest.raises(HomeworkAnswerConflictError):
            await review.handle(
                ReviewHomeworkAnswerCommand(
                    teacher_id=TEACHER,
                    homework_id=parent.id,
                    answer_id=answer.id,
                    status="graded",
                    grade=5,
                )
            )
        uploaded = await files.upload(
            STUDENT, parent.id, answer.id, file_id, BytesIO(b"answer")
        )
        assert uploaded.upload_status == "ready"
        file = await download(STUDENT)
        keys.append(file.storage_key)
        with storage.open(file.storage_key) as stream:
            assert stream.read() == b"answer"
        assert (
            await files.upload(
                STUDENT, parent.id, answer.id, file_id, BytesIO(b"answer")
            )
        ).id == file_id
        returned = await review.handle(
            ReviewHomeworkAnswerCommand(
                teacher_id=TEACHER,
                homework_id=parent.id,
                answer_id=answer.id,
                status="returned",
                teacher_comment="Исправь",
            )
        )
        assert returned.status == "returned"
        # Исторический ready-файл читается, но уже не заменяется.
        assert (await download(STUDENT)).storage_key == keys[0]
        # Возврат с недогруженным файлом не разрешает менять старую попытку.
        next_answer = (
            await submit.handle(
                SubmitHomeworkAnswerCommand(
                    student_id=STUDENT,
                    homework_id=parent.id,
                    idempotency_key="next-file",
                    files=[metadata],
                )
            )
        ).answer
        with pytest.raises(HomeworkAnswerNotFoundError):
            await files.get_file(STUDENT, "student", parent.id, next_answer.id, file_id)
        await review.handle(
            ReviewHomeworkAnswerCommand(
                teacher_id=TEACHER,
                homework_id=parent.id,
                answer_id=next_answer.id,
                status="returned",
                teacher_comment="Нужен другой файл",
            )
        )
        with pytest.raises(HomeworkAnswerConflictError):
            await files.upload(
                STUDENT,
                parent.id,
                next_answer.id,
                next_answer.files[0].id,
                BytesIO(b"answer"),
            )
        # Загрузка уже дошла до MinIO, но преподаватель успел вернуть работу.
        third = (
            await submit.handle(
                SubmitHomeworkAnswerCommand(
                    student_id=STUDENT,
                    homework_id=parent.id,
                    idempotency_key="racing-file",
                    files=[metadata],
                )
            )
        ).answer
        written, release = Event(), Event()
        original_put = storage.put

        def delayed_put(key, stream, size, content_type):
            original_put(key, stream, size, content_type)
            keys.append(key)
            written.set()
            if not release.wait(5):
                raise OSError("Test did not release upload")

        monkeypatch.setattr(storage, "put", delayed_put)
        uploading = asyncio.create_task(
            files.upload(
                STUDENT, parent.id, third.id, third.files[0].id, BytesIO(b"answer")
            )
        )
        try:
            assert await asyncio.to_thread(written.wait, 5)
            await review.handle(
                ReviewHomeworkAnswerCommand(
                    teacher_id=TEACHER,
                    homework_id=parent.id,
                    answer_id=third.id,
                    status="returned",
                    teacher_comment="Вернул во время загрузки",
                )
            )
        finally:
            release.set()
        with pytest.raises(HomeworkAnswerConflictError):
            await uploading
        async with uow() as unit:
            assert (
                await unit.answer_files.get_by_id(third.files[0].id)
            ).upload_status == "pending"
        future = datetime.now(UTC) + timedelta(hours=25)
        await cleanup_files(storage, uow, clock=lambda: future)
        # Подтверждённый файл первой попытки остаётся, проигравший объект удалён.
        with storage.open(keys[0]) as stream:
            assert stream.read() == b"answer"
        with pytest.raises(OSError), storage.open(keys[-1]):
            pass

    try:
        asyncio.run(run())
    finally:
        for key in keys:
            storage.delete(key)
        storage.close()
