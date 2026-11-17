"""Проверяет завершение, повторы и защиту нового периода от старой команды."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from journal_service.application.events import StudentClassPeriodEndedEvent
from journal_service.application.ports.errors import StudentClassPeriodConflictError
from journal_service.domain.student_class_period import StudentClassPeriod


@pytest.fixture
def setup():
    """Внешняя граница хранения; настоящая логика завершения не подменяется."""
    from journal_service.application.end_student_class_period import (
        EndStudentClassPeriodCommand,
        EndStudentClassPeriodHandler,
    )

    student = uuid4()
    joined = datetime(2026, 9, 1, tzinfo=UTC)
    left = datetime(2026, 10, 16, tzinfo=UTC)
    opened = StudentClassPeriod(student, 1, id=10, joined_at=joined)
    closed = StudentClassPeriod(student, 1, id=10, joined_at=joined, left_at=left)
    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.class_periods.get_period_for_update = AsyncMock(return_value=opened)
    uow.class_periods.get_current_period_for_student = AsyncMock(return_value=None)
    uow.class_periods.close_period = AsyncMock(return_value=closed)
    uow.outbox.add_event = AsyncMock()
    command = EndStudentClassPeriodCommand(
        student_id=student,
        expected_period_id=10,
        actor_id="42",
        request_id=str(uuid4()),
    )
    return SimpleNamespace(
        command=command,
        uow=uow,
        closed=closed,
        handler=EndStudentClassPeriodHandler(Mock(return_value=uow)),
    )


def test_end_closes_expected_and_records_server_time(setup):
    """Завершение не создаёт новый период и записывает идентичность закрытого."""
    assert asyncio.run(setup.handler.handle(setup.command)) is None
    setup.uow.class_periods.close_period.assert_awaited_once_with(10)
    setup.uow.outbox.add_event.assert_awaited_once()
    event = setup.uow.outbox.add_event.await_args.args[0]
    assert isinstance(event, StudentClassPeriodEndedEvent)
    assert event.student_id == setup.command.student_id
    assert event.period_id == 10 and event.class_id == 1
    assert event.occurred_at == setup.closed.left_at
    assert event.actor_id == "42" and event.request_id == setup.command.request_id
    setup.uow.class_periods.create_period.assert_not_called()


@pytest.mark.parametrize("expected_exists", [False, True])
def test_end_without_current_is_idempotent(setup, expected_exists):
    """Отсутствие активного периода не создаёт события при повторе."""
    setup.uow.class_periods.get_period_for_update.return_value = (
        setup.closed if expected_exists else None
    )
    assert asyncio.run(setup.handler.handle(setup.command)) is None
    setup.uow.class_periods.close_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


@pytest.mark.parametrize("expected_exists", [False, True])
def test_end_old_expected_cannot_close_other_current(setup, expected_exists):
    """Даже возвращение в тот же класс имеет новый период и не подходит старой форме."""
    setup.uow.class_periods.get_period_for_update.return_value = (
        setup.closed if expected_exists else None
    )
    setup.uow.class_periods.get_current_period_for_student.return_value = (
        StudentClassPeriod(
            setup.command.student_id, 1, id=11, joined_at=setup.closed.left_at
        )
    )
    with pytest.raises(StudentClassPeriodConflictError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.uow.class_periods.close_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


def test_end_conditional_close_failure_is_conflict(setup):
    """Неуспешный UPDATE не должен создавать ложное событие завершения."""
    setup.uow.class_periods.close_period.return_value = None
    with pytest.raises(StudentClassPeriodConflictError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.uow.outbox.add_event.assert_not_awaited()


def test_end_outbox_failure_reaches_transaction(setup):
    """Ошибка события не подавляется и заставляет UoW откатить закрытие."""
    failure = RuntimeError("outbox unavailable")
    setup.uow.outbox.add_event.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(setup.handler.handle(setup.command))
    assert caught.value is failure
    assert setup.uow.__aexit__.await_args.args[1] is failure


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_period_id", 0),
        ("expected_period_id", True),
        ("expected_period_id", "10"),
        ("expected_period_id", 2**31),
        ("student_id", "aaaaaaaa-0000-4000-8000-000000000001"),
        ("actor_id", "0"),
        ("actor_id", str(2**63)),
        ("request_id", "invalid"),
        ("extra", 1),
    ],
)
def test_end_command_rejects_invalid_input(setup, field, value):
    """Строгая команда не допускает неверные ID и подмену служебных полей."""
    command_type = type(setup.command)
    data = setup.command.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        command_type(**data)
