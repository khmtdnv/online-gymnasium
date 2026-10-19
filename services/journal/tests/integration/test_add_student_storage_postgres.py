"""Доказывает общую транзакцию периода и outbox на настоящем PostgreSQL."""

import asyncio
from uuid import uuid4

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from journal_service.application.events import StudentAddedToClassEvent
from journal_service.application.ports.errors import CurrentPeriodAlreadyExistsError
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod


def make_event(period) -> StudentAddedToClassEvent:
    """Строит событие из назначенных базой полей."""
    return StudentAddedToClassEvent(
        event_id=uuid4(),
        occurred_at=period.joined_at,
        request_id=str(uuid4()),
        actor_id="42",
        student_id=period.student_id,
        period_id=period.id,
        class_id=period.class_id,
    )


def test_period_and_event_commit_together(database_url: str) -> None:
    """Без общей сессии или commit одна из двух строк будет потеряна."""

    async def scenario() -> None:
        async with database(database_url) as (engine, factory):
            student = uuid4()
            async with factory() as uow:
                school_class = await uow.classes.create_class(Class("7А", 2026))
                period = await uow.class_periods.create_period(
                    StudentClassPeriod(student, school_class.id)
                )
                assert period.id is not None
                assert period.joined_at.utcoffset() is not None
                assert period.left_at is None
                event = make_event(period)
                await uow.outbox.add_event(event)
            async with engine.connect() as connection:
                stored = (
                    await connection.execute(
                        text(
                            "SELECT event_id, envelope, created_at, published_at FROM journal_event_outbox"
                        )
                    )
                ).one()
                assert stored.event_id == event.event_id
                assert stored.envelope["event_id"] == str(event.event_id)
                assert stored.envelope["payload"]["current"] == {
                    "period_id": period.id,
                    "class_id": school_class.id,
                }
                assert stored.created_at.utcoffset() is not None
                assert stored.published_at is None
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )

    asyncio.run(scenario())


def test_outbox_write_failure_rolls_back_new_period(database_url: str) -> None:
    """Настоящее нарушение PK outbox откатывает и уже flushed период."""

    async def scenario() -> None:
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                school_class = await uow.classes.create_class(Class("7А", 2026))
            with pytest.raises(IntegrityError):
                async with factory() as uow:
                    period = await uow.class_periods.create_period(
                        StudentClassPeriod(uuid4(), school_class.id)
                    )
                    event = make_event(period)
                    await uow.outbox.add_event(event)
                    await uow.outbox.add_event(event)
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 0
                )
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM journal_event_outbox")
                    )
                    == 0
                )
                assert (
                    await connection.scalar(text("SELECT count(*) FROM classes")) == 1
                )

    asyncio.run(scenario())


def test_concurrent_period_writes_have_one_winner(database_url: str) -> None:
    """Partial unique index оставляет одну строку и событие при гонке."""

    async def scenario() -> None:
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                school_class = await uow.classes.create_class(Class("7А", 2026))
            student = uuid4()
            both_ready = asyncio.Event()
            ready_count = 0

            async def write() -> bool:
                nonlocal ready_count
                try:
                    async with factory() as uow:
                        assert (
                            await uow.class_periods.get_current_period_for_student(
                                student
                            )
                            is None
                        )
                        ready_count += 1
                        if ready_count == 2:
                            both_ready.set()
                        await asyncio.wait_for(both_ready.wait(), 5)
                        period = await uow.class_periods.create_period(
                            StudentClassPeriod(student, school_class.id)
                        )
                        await uow.outbox.add_event(make_event(period))
                    return True
                except CurrentPeriodAlreadyExistsError:
                    return False

            outcomes = await asyncio.wait_for(
                asyncio.gather(write(), write(), return_exceptions=True), 10
            )
            assert outcomes.count(True) == 1
            assert outcomes.count(False) == 1
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM journal_event_outbox")
                    )
                    == 1
                )

    asyncio.run(scenario())
