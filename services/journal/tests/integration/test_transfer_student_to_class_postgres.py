"""Реальные транзакции и гонки перевода с сохранением истории и outbox."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from journal_service.application.class_periods import ClassPeriodResult
from journal_service.application.ports.errors import StudentClassPeriodConflictError
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo
from journal_service.application.transfer_student_to_class import (
    TransferStudentToClassCommand,
    TransferStudentToClassHandler,
)
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod
from journal_service.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from journal_service.infrastructure.student_class_period_repository import (
    SqlAlchemyStudentClassPeriodRepository,
)


async def seed(factory):
    """Создаёт исходный период и три класса в изолированной БД."""
    async with factory() as uow:
        classes = [
            await uow.classes.create_class(Class(name, 2026))
            for name in ("7А", "7Б", "7В")
        ]
        period = await uow.class_periods.create_period(
            StudentClassPeriod(uuid4(), classes[0].id)
        )
    return period, classes


def handler_for(factory, student_id):
    """Подменяет только внешний Gateway, локальная транзакция настоящая."""
    reader = SimpleNamespace(
        get_user=AsyncMock(
            return_value=GatewayUserInfo(id=student_id, role="student", is_active=True)
        )
    )
    return TransferStudentToClassHandler(factory, reader)


def command_for(period, target_class_id):
    """Каждая попытка использует исходный expected, а не свежую строку из БД."""
    return TransferStudentToClassCommand(
        student_id=period.student_id,
        target_class_id=target_class_id,
        expected_period_id=period.id,
        actor_id="42",
        request_id=str(uuid4()),
    )


@pytest.mark.parametrize("same_target", [True, False])
def test_concurrent_transfers_change_expected_period_once(database_url, same_target):
    """Из одного expected проходит один перевод даже при одинаковом назначении."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, classes = await seed(factory)
            handler = handler_for(factory, period.student_id)
            targets = [classes[1].id, classes[1].id if same_target else classes[2].id]
            commands = [command_for(period, target) for target in targets]
            barrier = asyncio.Barrier(2)
            original = SqlAlchemyStudentClassPeriodRepository.get_period_for_update

            async def synchronized_read(repository, student_id, period_id):
                await asyncio.wait_for(barrier.wait(), 5)
                return await original(repository, student_id, period_id)

            with patch.object(
                SqlAlchemyStudentClassPeriodRepository,
                "get_period_for_update",
                synchronized_read,
            ):
                outcomes = await asyncio.wait_for(
                    asyncio.gather(
                        *(handler.handle(command) for command in commands),
                        return_exceptions=True,
                    ),
                    15,
                )
            successes = [
                item for item in outcomes if isinstance(item, ClassPeriodResult)
            ]
            assert len(successes) == 1, outcomes
            assert (
                sum(
                    isinstance(item, StudentClassPeriodConflictError)
                    for item in outcomes
                )
                == 1
            ), outcomes
            winner = successes[0]
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT id, class_id, joined_at, left_at "
                            "FROM student_class_periods ORDER BY id"
                        )
                    )
                ).all()
                envelopes = (
                    await conn.scalars(
                        text("SELECT envelope FROM journal_event_outbox")
                    )
                ).all()
            assert len(rows) == 2
            assert rows[0].id == period.id
            assert rows[0].class_id == classes[0].id
            assert rows[0].left_at == rows[1].joined_at == winner.joined_at
            assert rows[1].id == winner.id
            assert rows[1].class_id in targets
            assert rows[1].left_at is None
            assert len(envelopes) == 1
            assert envelopes[0]["payload"] == {
                "operation": "transferred",
                "student_id": str(period.student_id),
                "previous": {"period_id": period.id, "class_id": classes[0].id},
                "current": {"period_id": winner.id, "class_id": winner.class_id},
            }
            winning_command = commands[outcomes.index(winner)]
            assert envelopes[0]["request_id"] == winning_command.request_id

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_point", ["new_period", "outbox"])
def test_transfer_sql_failure_restores_old_period(database_url, failure_point):
    """Даже уже выполненное закрытие откатывается при последующей SQL-ошибке."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, classes = await seed(factory)
            if failure_point == "new_period":
                original = SqlAlchemyStudentClassPeriodRepository.create_period

                async def invalid_insert(repository, supplied):
                    return await original(
                        repository,
                        StudentClassPeriod(
                            supplied.student_id,
                            2147483647,
                            joined_at=supplied.joined_at,
                        ),
                    )

                fault = patch.object(
                    SqlAlchemyStudentClassPeriodRepository,
                    "create_period",
                    invalid_insert,
                )
            else:
                original = SqlAlchemyOutboxRepository.add_event

                async def duplicate_event(repository, event):
                    await original(repository, event)
                    await original(repository, event)

                fault = patch.object(
                    SqlAlchemyOutboxRepository, "add_event", duplicate_event
                )
            with fault, pytest.raises(IntegrityError):
                await handler_for(factory, period.student_id).handle(
                    command_for(period, classes[1].id)
                )
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT id, class_id, left_at FROM student_class_periods")
                    )
                ).one()
                assert row.id == period.id
                assert row.class_id == classes[0].id
                assert row.left_at is None
                assert (
                    await conn.scalar(text("SELECT count(*) FROM journal_event_outbox"))
                    == 0
                )

    asyncio.run(scenario())


def test_return_to_previous_class_creates_new_period_and_rejects_old_expected(
    database_url,
):
    """Возврат в7А — третий период; старый ID не даёт no-op по совпадению класса."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            first, classes = await seed(factory)
            handler = handler_for(factory, first.student_id)
            second = await handler.handle(command_for(first, classes[1].id))
            third = await handler.handle(command_for(second, classes[0].id))
            assert len({first.id, second.id, third.id}) == 3
            with pytest.raises(StudentClassPeriodConflictError):
                await handler.handle(command_for(first, classes[0].id))
            async with engine.connect() as conn:
                history = (
                    await conn.execute(
                        text(
                            "SELECT id, class_id, joined_at, left_at "
                            "FROM student_class_periods ORDER BY id"
                        )
                    )
                ).all()
                assert len(history) == 3
                assert [row.class_id for row in history] == [
                    classes[0].id,
                    classes[1].id,
                    classes[0].id,
                ]
                assert history[0].left_at == history[1].joined_at
                assert history[1].left_at == history[2].joined_at
                assert history[2].left_at is None
                assert (
                    await conn.scalar(text("SELECT count(*) FROM journal_event_outbox"))
                    == 2
                )

    asyncio.run(scenario())


def test_matching_current_class_is_noop_on_postgres(database_url):
    """Совпавший открытый expected возвращается без новых строк и событий."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, classes = await seed(factory)
            result = await handler_for(factory, period.student_id).handle(
                command_for(period, classes[0].id)
            )
            assert result.id == period.id
            assert result.joined_at == period.joined_at
            async with engine.connect() as conn:
                assert (
                    await conn.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )
                assert (
                    await conn.scalar(text("SELECT count(*) FROM journal_event_outbox"))
                    == 0
                )

    asyncio.run(scenario())
