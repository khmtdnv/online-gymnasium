"""Проверяет поиск на отдельной PostgreSQL, а не на рабочей таблице пользователей."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.models.base import Base
from gateway_service.infrastructure.models.user import UserRow
from gateway_service.infrastructure.user_repository import SqlAlchemyUserRepository


@pytest.mark.skipif(
    not os.getenv("GATEWAY_TEST_DATABASE_URL"),
    reason="Нужна отдельная тестовая PostgreSQL",
)
def test_search_and_name_update_on_real_postgres():
    """Проверяет кириллицу, AND слов, роль, активность, literal %, лимит и UPDATE."""

    async def run():
        url = make_url(os.environ["GATEWAY_TEST_DATABASE_URL"])
        assert url.database and url.database.startswith("gateway_test_")
        engine = create_async_engine(url)
        created_ids = []
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            people = [
                User(
                    uuid4(),
                    "ivan@example.com",
                    Role.STUDENT,
                    "hash",
                    True,
                    "Иван",
                    "Петров",
                    "Сергеевич",
                ),
                User(
                    uuid4(),
                    "other@example.com",
                    Role.STUDENT,
                    "hash",
                    True,
                    "Максим",
                    "Петров",
                    "",
                ),
                User(
                    uuid4(),
                    "inactive@example.com",
                    Role.STUDENT,
                    "hash",
                    False,
                    "Иван",
                    "Петров",
                    "",
                ),
                User(
                    uuid4(),
                    "teacher@example.com",
                    Role.TEACHER,
                    "hash",
                    True,
                    "Иван",
                    "Петров",
                    "",
                ),
                User(
                    uuid4(),
                    "literal%_@example.com",
                    Role.STUDENT,
                    "hash",
                    True,
                    first_name="Тестовый",
                    last_name="Пользователь",
                ),
            ]
            created_ids = [user.id for user in people]
            async with factory() as session:
                repo = SqlAlchemyUserRepository(session)
                for user in people:
                    await repo.create_user(user)
                await session.commit()
            async with factory() as session:
                repo = SqlAlchemyUserRepository(session)
                for query in ("пЕТРОВ иВАН", "Серге Ив", "Ив Петр", "ivan@"):
                    assert [
                        u.id
                        for u in await repo.search_users(query, Role.STUDENT, True, 20)
                    ] == [people[0].id]
                assert [
                    u.id for u in await repo.search_users("%_", None, False, 20)
                ] == [people[4].id]
                assert await repo.search_users("' OR 1=1 --", None, False, 20) == []
                assert len(await repo.search_users("Петров", None, False, 1)) == 1
                assert len(await repo.search_users("Петров", None, False, 20)) == 4
                assert (
                    await repo.update_user_names(uuid4(), "Имя", "Фамилия", "") is None
                )
                updated = await repo.update_user_names(
                    people[0].id, "Иван", "Сидоров", ""
                )
                assert (
                    updated.last_name == "Сидоров" and updated.email == people[0].email
                )
                assert updated.password_hash == "hash" and updated.role is Role.STUDENT
                await session.rollback()
            async with factory() as session:
                assert (
                    await SqlAlchemyUserRepository(session).get_by_id(people[0].id)
                ).last_name == "Петров"
                for field in ("first_name", "last_name"):
                    for invalid in ("", "   ", "\t\n", None):
                        values = {
                            "id": uuid4(),
                            "email": "invalid-name@example.com",
                            "role": "student",
                            "password_hash": "hash",
                            "first_name": "Иван",
                            "last_name": "Петров",
                        }
                        values[field] = invalid
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(insert(UserRow).values(**values))
        finally:
            try:
                if created_ids:
                    async with engine.begin() as connection:
                        await connection.execute(
                            delete(UserRow).where(UserRow.id.in_(created_ids))
                        )
            finally:
                await engine.dispose()

    asyncio.run(run())
