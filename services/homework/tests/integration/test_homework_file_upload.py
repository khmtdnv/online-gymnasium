"""PostgreSQL сама выбирает одну готовую попытку и отклоняет просроченную."""

import asyncio
import hashlib
from datetime import timedelta
from io import BytesIO

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.domain.homework import Homework
from homework_service.infrastructure.file_upload import finish_upload, save_file
from homework_service.infrastructure.minio_file_storage import create_file_storage
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_domain_homework import data
from tests.test_homework_files import file_input

pytestmark = pytest.mark.integration


async def create_pending(factory):
    async with SqlAlchemyUnitOfWork(factory) as uow:
        homework = await uow.homeworks.add(Homework(**data()))
        files = await uow.files.add_files(
            homework.id, [HomeworkFileInput(**file_input())]
        )
    return files[0]


def test_two_concurrent_updates_choose_one_key_without_overwriting_it(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        file = await create_pending(factory)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            started_at = await uow.files.get_current_time()

        async def mark(key):
            async with SqlAlchemyUnitOfWork(factory) as uow:
                return await uow.files.mark_ready(file.id, key, started_at)

        results = await asyncio.gather(mark("homework/1/a"), mark("homework/1/b"))
        assert sum(result is not None for result in results) == 1
        winner = next(result for result in results if result is not None)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            stored = await uow.files.get_by_id(file.id)
        assert (
            stored.storage_key == winner.storage_key and stored.upload_status == "ready"
        )

    asyncio.run(run())


def test_expired_or_future_attempt_cannot_become_ready(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        file = await create_pending(factory)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            now = await uow.files.get_current_time()
            assert now.utcoffset() is not None
            assert (
                await uow.files.mark_ready(
                    file.id, "homework/old", now - timedelta(hours=2)
                )
                is None
            )
            assert (
                await uow.files.mark_ready(
                    file.id, "homework/future", now + timedelta(hours=2)
                )
                is None
            )
        async with SqlAlchemyUnitOfWork(factory) as uow:
            stored = await uow.files.get_by_id(file.id)
        assert stored.upload_status == "pending" and stored.storage_key is None

    asyncio.run(run())


def test_two_real_uploads_keep_one_object_and_return_the_same_ready_file(
    engine, minio_settings
):
    """Два потока MinIO и две транзакции PostgreSQL сходятся к одному вложению."""
    storage = create_file_storage(minio_settings)
    keys = []
    factory = async_sessionmaker(engine, expire_on_commit=False)
    content = "Пример решения".encode()

    def uow_factory():
        return SqlAlchemyUnitOfWork(factory)

    async def run():
        async with uow_factory() as uow:
            homework = await uow.homeworks.add(Homework(**data()))
            files = await uow.files.add_files(
                homework.id,
                [
                    HomeworkFileInput(
                        file_name="answer.txt",
                        size_bytes=len(content),
                        content_type="text/plain",
                        content_sha256=hashlib.sha256(content).hexdigest(),
                    )
                ],
            )
        file = files[0]

        async def upload():
            with BytesIO(content) as stream:
                key, started_at = await save_file(file, stream, uow_factory, storage)
            keys.append(key)
            return await finish_upload(file, key, started_at, uow_factory, storage)

        results = await asyncio.gather(upload(), upload())
        assert results[0] == results[1] and results[0].upload_status == "ready"
        assert len(set(keys)) == 2
        async with uow_factory() as uow:
            saved = await uow.files.get_by_id(file.id)
        assert saved.storage_key in keys
        with storage.open(saved.storage_key) as stream:
            assert stream.read() == content
        loser = next(key for key in keys if key != saved.storage_key)
        with pytest.raises(OSError), storage.open(loser):
            pass

    try:
        asyncio.run(run())
    finally:
        for key in keys:
            storage.delete(key)
        storage.close()
