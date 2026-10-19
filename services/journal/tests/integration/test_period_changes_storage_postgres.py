"""Проверяет блокировку, серверную границу и rollback на изолированной PG."""

import asyncio
from uuid import uuid4

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from journal_service.application.events import StudentAddedToClassEvent
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod


async def seed(factory):
    """Создаёт два класса и один открытый период только в тестовой БД."""
    async with factory() as uow:
        first = await uow.classes.create_class(Class("7А", 2026))
        second = await uow.classes.create_class(Class("7Б", 2026))
        period = await uow.class_periods.create_period(
            StudentClassPeriod(uuid4(), first.id)
        )
    return period, second


def test_lock_selects_exact_student_period_including_closed(database_url):
    """Чужой student/ID не подходит; закрытая строка доступна для stale-проверки."""

    async def scenario():
        async with database(database_url) as (_, factory):
            period, _ = await seed(factory)
            async with factory() as uow:
                repo = uow.class_periods
                assert await repo.get_period_for_update(uuid4(), period.id) is None
                assert await repo.get_period_for_update(period.student_id, -1) is None
                found = await repo.get_period_for_update(period.student_id, period.id)
                assert found == period
                closed = await repo.close_period(period.id)
                found = await repo.get_period_for_update(period.student_id, period.id)
                assert found.left_at == closed.left_at

    asyncio.run(scenario())


def test_close_changes_once_and_returns_server_boundary(database_url):
    """Повтор закрытия не меняет дату; отсутствующий ID не обновляет другие строки."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, _ = await seed(factory)
            async with factory() as uow:
                assert await uow.class_periods.close_period(-1) is None
                closed = await uow.class_periods.close_period(period.id)
                assert closed.id == period.id
                assert closed.student_id == period.student_id
                assert closed.joined_at == period.joined_at
                assert closed.left_at >= period.joined_at
                assert closed.left_at.utcoffset() is not None
                assert await uow.class_periods.close_period(period.id) is None
            async with engine.connect() as conn:
                assert (
                    await conn.scalar(
                        text("SELECT left_at FROM student_class_periods WHERE id=:id"),
                        {"id": period.id},
                    )
                    == closed.left_at
                )

    asyncio.run(scenario())


def test_transfer_boundary_is_one_database_time_after_transaction_start(database_url):
    """clock_timestamp, а не transaction-start now(); явная дата не теряется."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, target = await seed(factory)
            async with factory() as uow:
                locked = await uow.class_periods.get_period_for_update(
                    period.student_id, period.id
                )
                assert locked.id == period.id
                async with engine.connect() as conn:
                    before_close = await conn.scalar(text("SELECT clock_timestamp()"))
                closed = await uow.class_periods.close_period(period.id)
                new = await uow.class_periods.create_period(
                    StudentClassPeriod(
                        period.student_id, target.id, joined_at=closed.left_at
                    )
                )
                assert closed.left_at >= before_close
                assert new.joined_at == closed.left_at
                assert new.id != closed.id
                assert new.left_at is None
            async with factory() as uow:
                current = await uow.class_periods.get_current_period_for_student(
                    period.student_id
                )
                assert current.id == new.id

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_close_and_new_period(database_url):
    """Реальный конфликт PK события откатывает обе стороны перевода."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, target = await seed(factory)
            with pytest.raises(IntegrityError):
                async with factory() as uow:
                    await uow.class_periods.get_period_for_update(
                        period.student_id, period.id
                    )
                    closed = await uow.class_periods.close_period(period.id)
                    new = await uow.class_periods.create_period(
                        StudentClassPeriod(
                            period.student_id, target.id, joined_at=closed.left_at
                        )
                    )
                    event = StudentAddedToClassEvent(
                        event_id=uuid4(),
                        occurred_at=new.joined_at,
                        request_id=str(uuid4()),
                        actor_id="42",
                        student_id=new.student_id,
                        period_id=new.id,
                        class_id=new.class_id,
                    )
                    await uow.outbox.add_event(event)
                    await uow.outbox.add_event(event)
            async with engine.connect() as conn:
                stored = (
                    await conn.execute(
                        text("SELECT id, left_at FROM student_class_periods")
                    )
                ).one()
                assert stored.id == period.id
                assert stored.left_at is None
                assert (
                    await conn.scalar(text("SELECT count(*) FROM journal_event_outbox"))
                    == 0
                )

    asyncio.run(scenario())


def test_waiting_lock_returns_committed_closed_version(database_url):
    """Вторая транзакция ждёт реальный row lock и видит закрытие после commit."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, _ = await seed(factory)
            ready = asyncio.Event()
            reader_pid = None

            async def wait_for_period():
                nonlocal reader_pid
                async with factory() as uow:
                    reader_pid = await uow._session.scalar(
                        text("SELECT pg_backend_pid()")
                    )
                    ready.set()
                    return await uow.class_periods.get_period_for_update(
                        period.student_id, period.id
                    )

            waiter = None
            try:
                async with factory() as owner:
                    await owner.class_periods.get_period_for_update(
                        period.student_id, period.id
                    )
                    closed = await owner.class_periods.close_period(period.id)
                    waiter = asyncio.create_task(wait_for_period())
                    await asyncio.wait_for(ready.wait(), 5)
                    async with asyncio.timeout(5):
                        while True:
                            async with engine.connect() as conn:
                                waiting = await conn.scalar(
                                    text(
                                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity "
                                        "WHERE pid=:pid"
                                    ),
                                    {"pid": reader_pid},
                                )
                            if waiting:
                                break
                            if waiter.done():
                                pytest.fail(
                                    "Чтение завершилось до освобождения row lock"
                                )
                            await asyncio.sleep(0.01)
                result = await asyncio.wait_for(waiter, 5)
                assert result.left_at == closed.left_at
                assert result.id == period.id
            finally:
                if waiter is not None and not waiter.done():
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)

    asyncio.run(scenario())
