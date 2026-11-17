"""Границы транзакции принадлежат Unit of Work."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.parametrize("failure", [None, "body", "commit"])
def test_transaction_closes_and_rolls_back_on_error(failure):
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    session = Mock(commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock())
    if failure == "commit":
        session.commit.side_effect = RuntimeError("commit unavailable")

    async def run():
        async with SqlAlchemyUnitOfWork(lambda: session) as uow:
            assert uow.homeworks is not None
            if failure == "body":
                raise RuntimeError("body failed")

    if failure:
        with pytest.raises(RuntimeError):
            asyncio.run(run())
    else:
        asyncio.run(run())
    session.close.assert_awaited_once()
    assert session.rollback.await_count == (1 if failure else 0)


def test_separate_uow_instances_open_separate_sessions():
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    sessions = [
        Mock(commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock())
        for _ in range(2)
    ]
    factory = Mock(side_effect=sessions)

    async def run():
        async with (
            SqlAlchemyUnitOfWork(factory) as first,
            SqlAlchemyUnitOfWork(factory) as second,
        ):
            assert first.homeworks is not second.homeworks

    asyncio.run(run())
    assert factory.call_count == 2
