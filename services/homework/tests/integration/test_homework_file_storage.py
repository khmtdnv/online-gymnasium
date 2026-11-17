"""Реальная PostgreSQL: ожидаемые файлы и ДЗ сохраняются одной транзакцией."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.test_create_homework import NOW, Journal, Schedule, command, lesson
from tests.test_domain_homework import data
from tests.test_homework_files import file_input

pytestmark = pytest.mark.integration


def test_create_reserves_pending_files_and_keeps_text_visible(engine):
    from homework_service.application.homework import CreateHomeworkHandler
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        handler = CreateHomeworkHandler(
            lambda: SqlAlchemyUnitOfWork(factory),
            Schedule(lesson(), None),
            Journal(),
            lambda: NOW,
        )
        result = await handler.handle(command(files=[file_input(), file_input()]))
        assert [item.id for item in result.files] == [1, 2]
        assert all(item.upload_status == "pending" for item in result.files)
        assert all(item.homework_id == result.id for item in result.files)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert (
                await uow.homeworks.get_by_id(result.id)
            ).description == "Решить задачи 1–3"
            grouped = await uow.files.list_for_homeworks([result.id, 999])
            assert [item.id for item in grouped[result.id]] == [1, 2]
            assert grouped.get(999, []) == []
            first = await uow.files.get_by_id(1)
            assert first.content_sha256 == "a" * 64
            assert first.storage_key is None
            assert await uow.files.get_by_id(999) is None

    asyncio.run(run())


def test_invalid_file_insert_rolls_back_parent_and_previous_file(engine):
    from homework_service.application.homework_files import HomeworkFileInput
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.models.homework_file import HomeworkFileRow
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        with pytest.raises(IntegrityError):
            async with SqlAlchemyUnitOfWork(factory) as uow:
                saved = await uow.homeworks.add(Homework(**data()))
                await uow.files.add_files(saved.id, [HomeworkFileInput(**file_input())])
                # Сбой реального SQL INSERT, не имитация rollback в memory fake.
                uow._session.add(
                    HomeworkFileRow(
                        homework_id=saved.id,
                        upload_status="ready",
                        storage_key=None,
                        **file_input(),
                    )
                )
                await uow._session.flush()
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM homework_assignments")
                )
                == 0
            )
            assert (
                await connection.scalar(text("SELECT count(*) FROM homework_files"))
                == 0
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"size_bytes": 0},
        {"upload_status": "bogus"},
        {"upload_status": "ready", "storage_key": None},
        {"upload_status": "pending", "storage_key": "unexpected"},
        {"content_sha256": "bad"},
        {"file_name": ""},
    ],
)
def test_raw_database_rejects_invalid_file_metadata(engine, changes):
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.models.homework_file import HomeworkFileRow
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run():
        async with SqlAlchemyUnitOfWork(factory) as uow:
            saved = await uow.homeworks.add(Homework(**data()))
        async with factory() as session:
            session.add(
                HomeworkFileRow(
                    **(
                        {
                            "homework_id": saved.id,
                            "upload_status": "pending",
                            "storage_key": None,
                        }
                        | file_input()
                        | changes
                    )
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

    asyncio.run(run())


def test_files_migration_downgrade_preserves_existing_homework(engine, migrate):
    from homework_service.application.homework_files import HomeworkFileInput
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create():
        async with SqlAlchemyUnitOfWork(factory) as uow:
            saved = await uow.homeworks.add(Homework(**data()))
            await uow.files.add_files(saved.id, [HomeworkFileInput(**file_input())])

    asyncio.run(create())
    migrate("c24f07d91a68", "downgrade")

    async def verify():
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM homework_assignments")
                )
                == 1
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('homework_files')"))
                is None
            )

    asyncio.run(verify())
    migrate("head")
