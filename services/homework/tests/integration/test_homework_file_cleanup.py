"""Настоящие PG/MinIO; время уборки ускоряется только внедрёнными тестовыми часами."""

import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from secrets import token_hex

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.cleanup_files import cleanup_files
from homework_service.domain.homework import Homework
from homework_service.infrastructure.minio_file_storage import create_file_storage
from homework_service.infrastructure.models.homework_file import HomeworkFileRow
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_domain_homework import data

pytestmark = pytest.mark.integration


def test_cleanup_preserves_confirmed_object_and_pending_rows_and_is_repeatable(
    engine, minio_settings
):
    storage = create_file_storage(minio_settings)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def uow():
        return SqlAlchemyUnitOfWork(sessions)

    keys = []

    async def run():
        async with uow() as unit:
            parent = await unit.homeworks.add(Homework(**data()))
            files = await unit.files.add_files(
                parent.id,
                [
                    HomeworkFileInput(
                        file_name="one.txt",
                        size_bytes=1,
                        content_type="text/plain",
                        content_sha256="a" * 64,
                    ),
                    HomeworkFileInput(
                        file_name="two.txt",
                        size_bytes=1,
                        content_type="text/plain",
                        content_sha256="a" * 64,
                    ),
                ],
            )
        for file in files:
            key = f"homework/{parent.id}/files/{file.id}/{token_hex(16)}"
            keys.append(key)
            storage.put(key, BytesIO(b"x"), 1, "text/plain")
        async with uow() as unit:
            started = await unit.files.get_current_time()

        async def finalize():
            async with uow() as unit:
                assert (
                    await unit.files.mark_ready(files[0].id, keys[0], started)
                    is not None
                )

        # Уборка одновременно с финализацией не трогает свежие байты.
        results = await asyncio.gather(finalize(), cleanup_files(storage, uow))
        assert results[1] == 0
        future = datetime.now(UTC) + timedelta(hours=25)
        assert await cleanup_files(storage, uow, clock=lambda: future) >= 1
        assert await cleanup_files(storage, uow, clock=lambda: future) == 0
        with storage.open(keys[0]) as stream:
            assert stream.read() == b"x"
        with pytest.raises(OSError), storage.open(keys[1]):
            pass
        async with sessions() as session:
            rows = (
                await session.scalars(
                    select(HomeworkFileRow).order_by(HomeworkFileRow.id)
                )
            ).all()
            assert [(row.id, row.upload_status) for row in rows] == [
                (files[0].id, "ready"),
                (files[1].id, "pending"),
            ]
        # Старая попытка не может опубликовать уже доступный уборке объект.
        async with uow() as unit:
            assert (
                await unit.files.mark_ready(
                    files[1].id, keys[1], started - timedelta(hours=25)
                )
                is None
            )

    try:
        asyncio.run(run())
    finally:
        for key in keys:
            storage.delete(key)
        storage.close()
