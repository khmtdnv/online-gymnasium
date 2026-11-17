"""Проверяет управление транзакцией; реальная PostgreSQL здесь не используется."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def test_successful_exit_commits_then_closes_session() -> None:
    """Успешный сценарий сохраняет изменения перед закрытием сессии."""
    from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    session = Mock(spec=AsyncSession)
    events = []

    async def commit() -> None:
        events.append("commit")

    async def close() -> None:
        events.append("close")

    session.commit = AsyncMock(side_effect=commit)
    session.close = AsyncMock(side_effect=close)
    session.rollback = AsyncMock()

    async def scenario() -> None:
        async with SqlAlchemyUnitOfWork(lambda: session):
            pass

    asyncio.run(scenario())

    assert events == ["commit", "close"]
    session.rollback.assert_not_awaited()


def test_class_and_period_repositories_share_one_session_and_transaction() -> None:
    """Оба репозитория читают через одну сессию и завершаются одним commit."""
    from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    session = Mock(spec=AsyncSession)
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    factory = Mock(return_value=session)

    async def scenario() -> None:
        from uuid import UUID

        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert uow.classes._session is session
            assert uow.class_periods._session is session
            assert uow.outbox._session is session
            assert await uow.classes.get_class_by_id(7) is None
            assert (
                await uow.class_periods.get_current_period_for_student(
                    UUID("aaaaaaaa-0000-4000-8000-000000000001")
                )
                is None
            )

    asyncio.run(scenario())
    factory.assert_called_once_with()
    assert session.execute.await_count == 2
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once_with()


def test_body_failure_rolls_back_and_preserves_exception() -> None:
    """Ошибка сценария отменяет транзакцию и не подавляется."""
    from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    session = Mock(spec=AsyncSession)
    failure = ValueError("scenario failed")

    async def scenario() -> None:
        async with SqlAlchemyUnitOfWork(lambda: session):
            raise failure

    with pytest.raises(ValueError) as caught:
        asyncio.run(scenario())

    assert caught.value is failure
    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()
    session.close.assert_awaited_once_with()


@pytest.mark.parametrize("operation", ["commit", "rollback"])
def test_transaction_failure_still_closes_session(operation: str) -> None:
    """Даже сбой завершения транзакции не пропускает закрытие сессии."""
    from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    session = Mock(spec=AsyncSession)
    failure = RuntimeError("transaction failed")
    getattr(session, operation).side_effect = failure

    async def scenario() -> None:
        async with SqlAlchemyUnitOfWork(lambda: session):
            if operation == "rollback":
                raise ValueError("scenario failed")

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(scenario())

    assert caught.value is failure
    session.close.assert_awaited_once_with()


def test_each_unit_of_work_uses_its_own_session_for_repository() -> None:
    """Два UoW направляют запросы своих репозиториев в разные сессии."""
    from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    sessions = [Mock(spec=AsyncSession), Mock(spec=AsyncSession)]
    factory = Mock(side_effect=sessions)

    async def scenario() -> None:
        for _ in range(2):
            uow = SqlAlchemyUnitOfWork(factory)
            async with uow as entered:
                assert entered is uow
                await entered.classes.list_classes(None, 50, 0)

    for session in sessions:
        result = Mock()
        result.scalars.return_value.all.return_value = []
        session.execute.return_value = result

    asyncio.run(scenario())

    for session in sessions:
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once_with()
        session.close.assert_awaited_once_with()
