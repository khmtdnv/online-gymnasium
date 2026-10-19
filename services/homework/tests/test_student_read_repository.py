"""Индекс и фильтр списка согласованы с пагинацией текущего класса."""

import asyncio
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex


def test_repository_filters_orders_and_paginates():
    from homework_service.infrastructure.homework_repository import (
        SqlAlchemyHomeworkRepository,
    )

    seen = []

    async def scalars(statement):
        seen.append(
            str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        )
        return SimpleNamespace(all=list)

    assert (
        asyncio.run(
            SqlAlchemyHomeworkRepository(
                SimpleNamespace(scalars=scalars)
            ).list_for_class(7, 2, 1)
        )
        == []
    )
    sql = seen[0]
    assert "homework_assignments.class_id = 7" in sql
    assert (
        "ORDER BY homework_assignments.created_at DESC, homework_assignments.id DESC"
        in sql
    )
    assert "LIMIT 2 OFFSET 1" in sql


def test_class_read_index_matches_query_order():
    from homework_service.infrastructure.models.homework import HomeworkRow

    index = next(
        (
            i
            for i in HomeworkRow.__table__.indexes
            if i.name == "homework_assignments_class_created_id_idx"
        ),
        None,
    )
    assert index is not None
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "(class_id, created_at DESC, id DESC)" in sql
