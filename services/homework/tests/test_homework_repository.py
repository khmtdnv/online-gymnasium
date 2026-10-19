"""Переводим только конкретный конфликт уникальности, не все ошибки БД."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from tests.test_domain_homework import data


@pytest.mark.parametrize(
    ("sqlstate", "constraint", "translated"),
    [
        ("23505", "homework_assignments_issued_lesson_unique", True),
        ("23505", "homework_assignments_pkey", False),
        ("23514", "homework_assignments_one_due", False),
        (None, None, False),
    ],
)
def test_translates_only_issued_lesson_conflict(sqlstate, constraint, translated):
    from homework_service.application.ports.errors import HomeworkAlreadyExistsError
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.homework_repository import (
        SqlAlchemyHomeworkRepository,
    )

    # SQLAlchemy wraps driver errors. Keep that boundary real, replace only flush.
    driver = RuntimeError("database rejected insert")
    driver.sqlstate, driver.constraint_name = sqlstate, constraint
    error = IntegrityError("INSERT", {}, driver)
    session = Mock(flush=AsyncMock(side_effect=error))
    repository = SqlAlchemyHomeworkRepository(session)
    with pytest.raises(HomeworkAlreadyExistsError if translated else IntegrityError):
        asyncio.run(repository.add(Homework(**data())))


def test_absent_rows_return_none():
    from homework_service.infrastructure.homework_repository import (
        SqlAlchemyHomeworkRepository,
    )

    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    repo = SqlAlchemyHomeworkRepository(session)
    assert asyncio.run(repo.get_by_id(5)) is None
    assert asyncio.run(repo.get_by_issued_lesson_id(11)) is None
