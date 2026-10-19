"""Пакетный SELECT ограничен запрошенными ID и детерминированно упорядочен."""

import asyncio
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql


def test_get_many_emits_in_filter_and_id_order():
    from schedule_service.infrastructure.lesson_repository import (
        SqlAlchemyLessonRepository,
    )

    statements = []

    async def scalars(statement):
        statements.append(
            str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        )
        return SimpleNamespace(all=list)

    result = asyncio.run(
        SqlAlchemyLessonRepository(SimpleNamespace(scalars=scalars)).get_many([12, 11])
    )
    assert result == []
    assert len(statements) == 1
    assert " IN (12, 11)" in statements[0]
    assert "ORDER BY scheduled_lessons.id" in statements[0]
