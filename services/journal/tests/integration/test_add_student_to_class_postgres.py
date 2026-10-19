"""Проверяет гонки обработчика и откат периода с outbox на PostgreSQL."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from journal_service.application.add_student_to_class import (
    AddStudentToClassCommand,
    AddStudentToClassHandler,
    AddStudentToClassResult,
)
from journal_service.application.ports.errors import StudentClassConflictError
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo
from journal_service.domain.school_class import Class
from journal_service.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from journal_service.infrastructure.student_class_period_repository import (
    SqlAlchemyStudentClassPeriodRepository,
)


@pytest.mark.parametrize("same_class", [True, False])
def test_concurrent_handlers_leave_one_period_and_event(database_url, same_class):
    """Два первых чтения None не должны дать два эффекта или ложный успех."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                first = await uow.classes.create_class(Class("8А", 2026))
                second = await uow.classes.create_class(Class("8Б", 2026))
            student = uuid4()
            reader = SimpleNamespace(
                get_user=AsyncMock(
                    return_value=GatewayUserInfo(
                        id=student, role="student", is_active=True
                    )
                )
            )
            handler = AddStudentToClassHandler(factory, reader)
            barrier = asyncio.Barrier(2)
            original = SqlAlchemyStudentClassPeriodRepository.create_period

            async def synchronized_create(repository, period):
                await asyncio.wait_for(barrier.wait(), 5)
                return await original(repository, period)

            commands = [
                AddStudentToClassCommand(
                    student_id=student,
                    class_id=class_id,
                    actor_id="42",
                    request_id=str(uuid4()),
                )
                for class_id in (first.id, first.id if same_class else second.id)
            ]
            with patch.object(
                SqlAlchemyStudentClassPeriodRepository,
                "create_period",
                synchronized_create,
            ):
                outcomes = await asyncio.wait_for(
                    asyncio.gather(
                        *(handler.handle(command) for command in commands),
                        return_exceptions=True,
                    ),
                    15,
                )
            successes = [
                result
                for result in outcomes
                if isinstance(result, AddStudentToClassResult)
            ]
            if same_class:
                assert len(successes) == 2, outcomes
                assert sorted(result.created for result in successes) == [False, True]
                assert successes[0].period.id == successes[1].period.id
            else:
                assert len(successes) == 1, outcomes
                assert successes[0].created is True
                assert (
                    sum(
                        isinstance(result, StudentClassConflictError)
                        for result in outcomes
                    )
                    == 1
                )
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )
                envelopes = (
                    await connection.scalars(
                        text("SELECT envelope FROM journal_event_outbox")
                    )
                ).all()
                assert len(envelopes) == 1
                winner = next(result for result in successes if result.created)
                assert envelopes[0]["payload"]["current"] == {
                    "period_id": winner.period.id,
                    "class_id": winner.period.class_id,
                }

    asyncio.run(scenario())


def test_handler_outbox_failure_rolls_back_period(database_url):
    """Ошибка SQL после первой записи outbox не оставляет ни периода, ни события."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                school_class = await uow.classes.create_class(Class("8А", 2026))
            student = uuid4()
            reader = SimpleNamespace(
                get_user=AsyncMock(
                    return_value=GatewayUserInfo(
                        id=student, role="student", is_active=True
                    )
                )
            )
            original = SqlAlchemyOutboxRepository.add_event

            async def duplicate_event(repository, event):
                await original(repository, event)
                await original(repository, event)

            command = AddStudentToClassCommand(
                student_id=student,
                class_id=school_class.id,
                actor_id="42",
                request_id=str(uuid4()),
            )
            with (
                patch.object(SqlAlchemyOutboxRepository, "add_event", duplicate_event),
                pytest.raises(IntegrityError),
            ):
                await AddStudentToClassHandler(factory, reader).handle(command)
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

    asyncio.run(scenario())
