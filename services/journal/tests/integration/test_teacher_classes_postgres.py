"""Реальные PK/FK и конкурентная запись назначений в отдельной PostgreSQL."""

import asyncio
from uuid import uuid4

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from journal_service.application.ports.errors import TeacherAlreadyAssignedError
from journal_service.domain.school_class import Class


def test_unique_pair_concurrency_and_foreign_key(database_url):
    async def scenario():
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                saved = await uow.classes.create_class(
                    Class(name="7А", study_year=2026)
                )
            teacher = uuid4()

            async def add():
                async with factory() as uow:
                    await uow.teacher_classes.add(teacher, saved.id)

            results = await asyncio.gather(add(), add(), return_exceptions=True)
            assert sum(isinstance(x, TeacherAlreadyAssignedError) for x in results) == 1
            assert sum(x is None for x in results) == 1
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM teacher_classes")
                    )
                    == 1
                )
            with pytest.raises(IntegrityError):
                async with factory() as uow:
                    await uow.teacher_classes.add(uuid4(), 2147483647)
            async with factory() as uow:
                assert [
                    x.id
                    for x in await uow.teacher_classes.list_classes_for_teacher(
                        teacher, 50, 0
                    )
                ] == [saved.id]
                assert await uow.teacher_classes.remove(teacher, saved.id)
            async with factory() as uow:
                assert not await uow.teacher_classes.remove(teacher, saved.id)

    asyncio.run(scenario())


def test_concurrent_handlers_return_one_created_and_one_repeat(database_url):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from journal_service.application.ports.gateway_user_reader import GatewayUserInfo
    from journal_service.application.teacher_classes import (
        AssignTeacherToClassCommand,
        AssignTeacherToClassHandler,
        UnassignTeacherFromClassCommand,
        UnassignTeacherFromClassHandler,
    )

    async def scenario():
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                saved = await uow.classes.create_class(Class("7Б", 2026))
            teacher = uuid4()
            reader = SimpleNamespace(
                get_user=AsyncMock(
                    return_value=GatewayUserInfo(
                        id=teacher, role="teacher", is_active=True
                    )
                )
            )
            command = AssignTeacherToClassCommand(teacher_id=teacher, class_id=saved.id)
            handler = AssignTeacherToClassHandler(factory, reader)
            results = await asyncio.gather(
                handler.handle(command), handler.handle(command)
            )
            assert sorted(x.created for x in results) == [False, True]
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM teacher_classes")
                    )
                    == 1
                )
            remove = UnassignTeacherFromClassHandler(factory)
            await remove.handle(
                UnassignTeacherFromClassCommand(teacher_id=teacher, class_id=saved.id)
            )

    asyncio.run(scenario())


def test_migration_roundtrip_preserves_existing_class(database_url):
    import os
    from pathlib import Path
    from unittest.mock import patch

    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def prepare():
        async with database(database_url) as (_, factory), factory() as uow:
            return (await uow.classes.create_class(Class("8А", 2026))).id

    saved_id = asyncio.run(prepare())
    service = Path(__file__).resolve().parents[2]
    config = Config(str(service / "alembic.ini"))
    config.set_main_option("script_location", str(service / "migrations"))

    async def check(exists):
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT to_regclass('teacher_classes')")
                    )
                    is not None
                ) is exists
                assert (
                    await connection.scalar(
                        text("SELECT name FROM classes WHERE id=:id"), {"id": saved_id}
                    )
                    == "8А"
                )
        finally:
            await engine.dispose()

    with patch.dict(os.environ, {"DATABASE_URL": database_url}):
        try:
            command.downgrade(config, "d79431f0c9b2")
            asyncio.run(check(False))
        finally:
            command.upgrade(config, "head")
    asyncio.run(check(True))
