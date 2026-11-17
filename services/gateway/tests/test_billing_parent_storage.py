"""Проверка родительского доступа на настоящих связях PostgreSQL."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.models.base import Base
from gateway_service.infrastructure.models.parent_student_link import (
    ParentStudentLinkRow,
)
from gateway_service.infrastructure.models.user import UserRow
from gateway_service.infrastructure.user_repository import SqlAlchemyUserRepository


@pytest.mark.skipif(
    not os.getenv("GATEWAY_TEST_DATABASE_URL"),
    reason="Нужна отдельная тестовая PostgreSQL",
)
def test_parent_children_read_uses_current_link_and_names():
    async def run():
        url = make_url(os.environ["GATEWAY_TEST_DATABASE_URL"])
        assert url.database.startswith("gateway_test_")
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        parent, child, other = uuid4(), uuid4(), uuid4()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with sessions() as session, session.begin():
                repo = SqlAlchemyUserRepository(session)
                for id_, role in (
                    (parent, Role.PARENT),
                    (child, Role.STUDENT),
                    (other, Role.STUDENT),
                ):
                    await repo.create_user(
                        User(
                            id_,
                            f"{id_}@example.test",
                            role,
                            "hash",
                            True,
                            "Иван",
                            "Петров",
                        )
                    )
                await repo.create_parent_student_link(parent, child)
            async with sessions() as session:
                repo = SqlAlchemyUserRepository(session)
                assert await repo.has_parent_student_link(parent, child)
                assert not await repo.has_parent_student_link(parent, other)
                assert [row.id for row in await repo.list_children(parent, 100)] == [
                    child
                ]
                assert (await repo.list_children(parent, 1))[0].last_name == "Петров"
        finally:
            # Удаляет только строки этого теста, не оставляя их для теста поиска.
            async with sessions() as session, session.begin():
                await session.execute(
                    delete(ParentStudentLinkRow).where(
                        ParentStudentLinkRow.parent_id == parent
                    )
                )
                await session.execute(
                    delete(UserRow).where(UserRow.id.in_([parent, child, other]))
                )
            await engine.dispose()

    asyncio.run(run())
