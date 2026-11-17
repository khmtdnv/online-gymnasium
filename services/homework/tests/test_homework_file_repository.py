"""Пакетное чтение не превращается в N запросов и не теряет связи вложений."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects import postgresql

from tests.test_homework_files import file_input


def test_empty_homework_page_does_not_query_database():
    from homework_service.infrastructure.homework_file_repository import (
        SqlAlchemyHomeworkFileRepository,
    )

    session = SimpleNamespace(
        scalars=AsyncMock(side_effect=AssertionError("unexpected SQL"))
    )
    assert (
        asyncio.run(SqlAlchemyHomeworkFileRepository(session).list_for_homeworks([]))
        == {}
    )


def test_batch_query_filters_parents_and_groups_detached_values():
    from homework_service.infrastructure.homework_file_repository import (
        SqlAlchemyHomeworkFileRepository,
    )

    rows = [
        SimpleNamespace(
            id=file_id,
            homework_id=homework_id,
            upload_status="pending",
            storage_key=None,
            **file_input(),
        )
        for file_id, homework_id in [(8, 51), (9, 52), (10, 51)]
    ]
    session = Mock(scalars=AsyncMock(return_value=rows))
    repo = SqlAlchemyHomeworkFileRepository(session)
    grouped = asyncio.run(repo.list_for_homeworks([51, 52]))
    assert [file.id for file in grouped[51]] == [8, 10]
    assert [file.id for file in grouped[52]] == [9]
    assert grouped[51][0].content_sha256 == "a" * 64
    statement = session.scalars.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "homework_files.homework_id IN (51, 52)" in sql
    assert "ORDER BY homework_files.id" in sql


def test_absent_file_is_not_an_empty_domain_record():
    from homework_service.infrastructure.homework_file_repository import (
        SqlAlchemyHomeworkFileRepository,
    )

    repo = SqlAlchemyHomeworkFileRepository(
        SimpleNamespace(scalar=AsyncMock(return_value=None))
    )
    assert asyncio.run(repo.get_by_id(999)) is None
