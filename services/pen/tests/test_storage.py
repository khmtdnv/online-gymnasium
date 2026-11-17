"""Реальная отдельная pen_test_* БД: повторы и конкурентные вставки."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_contracts import batch_data


def test_append_is_idempotent_and_serializes_concurrent_sequences():
    from pen_service.contracts import StrokeBatch
    from pen_service.storage import (
        Base,
        PenConflictError,
        PenPageFullError,
        PenPageRow,
        PenStore,
    )

    url = os.getenv("PEN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PEN_TEST_DATABASE_URL not configured")
    assert make_url(url).database.startswith("pen_test_")

    async def run():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        store = PenStore(async_sessionmaker(engine, expire_on_commit=False))
        student = uuid4()
        first = StrokeBatch.model_validate_json(json.dumps(batch_data()))
        try:
            saved = await store.append(1, student, first)
            assert await store.append(1, student, first) == saved
            with pytest.raises(PenConflictError):
                await store.append(
                    1, student, first.model_copy(update={"finished": False})
                )
            contenders = [
                StrokeBatch.model_validate_json(json.dumps(batch_data(sequence=2)))
                for _ in range(2)
            ]
            results = await asyncio.gather(
                *(store.append(1, student, batch) for batch in contenders),
                return_exceptions=True,
            )
            assert sum(isinstance(result, PenConflictError) for result in results) == 1
            rows = await store.history(1, student, after=0)
            assert [row.sequence for row in rows] == [1, 2]
            assert await store.history(1, uuid4(), after=0) == []
            assert [
                row.sequence for row in await store.history(1, student, after=1)
            ] == [2]
            # Одновременно создаётся ещё не существующая страница.
            other = uuid4()
            outcomes = await asyncio.gather(
                store.append(1, other, first),
                store.append(1, other, first),
                return_exceptions=True,
            )
            # batch_id принадлежит первой странице и не может переноситься.
            assert all(isinstance(item, PenConflictError) for item in outcomes)
            other_batch = first.model_copy(update={"batch_id": uuid4()})
            new = await asyncio.gather(
                store.append(1, other, other_batch), store.append(1, other, other_batch)
            )
            assert new[0] == new[1]
            async with store._sessions() as session, session.begin():
                await session.execute(
                    update(PenPageRow)
                    .where(PenPageRow.student_id == student)
                    .values(point_count=19999)
                )
            overflowing = StrokeBatch.model_validate_json(
                json.dumps(batch_data(sequence=3, points=[{"x": 0.2, "y": 0.5}] * 2))
            )
            with pytest.raises(PenPageFullError):
                await store.append(1, student, overflowing)
            assert len(await store.history(1, student, after=0)) == 2
            async with store._sessions() as session:
                page = await session.scalar(
                    select(PenPageRow).where(PenPageRow.student_id == student)
                )
                assert page.point_count == 19999 and page.last_sequence == 2
        finally:
            await engine.dispose()

    asyncio.run(run())
