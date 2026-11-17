"""Проверяет входную команду и сценарий добавления ученика.

Базы и HTTP нет: подменены только внешние границы сценария.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from journal_service.application.add_student_to_class import (
    AddStudentToClassCommand,
    AddStudentToClassHandler,
)
from journal_service.application.ports.errors import (
    ClassNotFoundError,
    CurrentPeriodAlreadyExistsError,
    InvalidStudentError,
    StudentClassConflictError,
    StudentNotFoundError,
    UserLookupUnavailableError,
)
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod

STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
REQUEST_ID = "bbbbbbbb-0000-4000-8000-000000000002"
JOINED_AT = datetime(2026, 10, 14, 12, tzinfo=UTC)


@pytest.fixture
def setup():
    """Подготавливает внешние границы; фиксирует порядок Gateway и транзакции."""
    command = AddStudentToClassCommand(
        student_id=STUDENT, class_id=10, actor_id="42", request_id=REQUEST_ID
    )
    saved = StudentClassPeriod(STUDENT, 10, id=123, joined_at=JOINED_AT)
    operations = []
    uow = Mock()
    uow.classes.get_class_by_id = AsyncMock(return_value=Class("7А", 2026, id=10))
    uow.class_periods.get_current_period_for_student = AsyncMock(return_value=None)
    uow.class_periods.create_period = AsyncMock(return_value=saved)
    uow.outbox.add_event = AsyncMock()

    async def enter():
        operations.append("enter")
        return uow

    async def exit_uow(*_args):
        operations.append("exit")

    async def get_user(user_id):
        assert user_id == STUDENT
        operations.append("gateway")
        return GatewayUserInfo(id=STUDENT, role="student", is_active=True)

    uow.__aenter__ = AsyncMock(side_effect=enter)
    uow.__aexit__ = AsyncMock(side_effect=exit_uow)
    reader = SimpleNamespace(get_user=AsyncMock(side_effect=get_user))
    factory = Mock(return_value=uow)
    return SimpleNamespace(
        command=command,
        saved=saved,
        operations=operations,
        uow=uow,
        reader=reader,
        factory=factory,
        handler=AddStudentToClassHandler(factory, reader),
    )


def test_add_student_saves_period_and_one_event_before_return(setup) -> None:
    """Проверяет серверные поля события и Gateway до открытия UoW."""
    result = asyncio.run(setup.handler.handle(setup.command))
    assert result.created is True
    assert result.period.id == 123
    assert result.period.student_id == STUDENT
    assert result.period.class_id == 10
    assert result.period.joined_at == JOINED_AT
    assert result.period.left_at is None
    assert setup.operations == ["gateway", "enter", "exit"]
    for method, parameter, expected in (
        (setup.uow.classes.get_class_by_id, "class_id", 10),
        (setup.uow.class_periods.get_current_period_for_student, "student_id", STUDENT),
    ):
        method.assert_awaited_once()
        received = method.await_args
        value = received.args[0] if received.args else received.kwargs[parameter]
        assert value == expected
    setup.uow.class_periods.create_period.assert_awaited_once()
    supplied = setup.uow.class_periods.create_period.call_args
    period = supplied.args[0] if supplied.args else supplied.kwargs["period"]
    assert period == StudentClassPeriod(STUDENT, 10)
    setup.uow.outbox.add_event.assert_awaited_once()
    supplied = setup.uow.outbox.add_event.call_args
    event = supplied.args[0] if supplied.args else supplied.kwargs["event"]
    assert isinstance(event.event_id, UUID)
    assert event.occurred_at == JOINED_AT
    assert event.student_id == STUDENT
    assert event.period_id == 123
    assert event.class_id == 10
    assert event.actor_id == "42"
    assert event.request_id == REQUEST_ID


def test_same_class_is_noop_and_preserves_period_id(setup) -> None:
    """Повтор не создаёт ни новую строку, ни событие."""
    setup.uow.class_periods.get_current_period_for_student.return_value = setup.saved
    result = asyncio.run(setup.handler.handle(setup.command))
    assert result.created is False
    assert result.period.id == 123
    setup.uow.class_periods.create_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


def test_other_class_is_conflict_not_transfer(setup) -> None:
    """Добавление не закрывает старый период и не переводит ученика."""
    setup.uow.class_periods.get_current_period_for_student.return_value = (
        StudentClassPeriod(STUDENT, 20, id=124, joined_at=JOINED_AT)
    )
    with pytest.raises(StudentClassConflictError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.uow.class_periods.create_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


@pytest.mark.parametrize(
    ("user", "error"),
    [
        (None, StudentNotFoundError),
        (
            GatewayUserInfo(id=STUDENT, role="teacher", is_active=True),
            InvalidStudentError,
        ),
        (
            GatewayUserInfo(id=STUDENT, role="parent", is_active=True),
            InvalidStudentError,
        ),
        (
            GatewayUserInfo(id=STUDENT, role="admin", is_active=True),
            InvalidStudentError,
        ),
        (
            GatewayUserInfo(id=STUDENT, role="student", is_active=False),
            InvalidStudentError,
        ),
    ],
)
def test_unfit_gateway_user_does_not_open_uow(setup, user, error) -> None:
    """Отсутствие, роль и активность проверяются до локальной записи."""
    setup.reader.get_user.side_effect = None
    setup.reader.get_user.return_value = user
    with pytest.raises(error):
        asyncio.run(setup.handler.handle(setup.command))
    setup.factory.assert_not_called()


def test_gateway_unavailable_does_not_open_uow(setup) -> None:
    """Неизвестность Gateway не трактуется как разрешение на запись."""
    setup.reader.get_user.side_effect = UserLookupUnavailableError
    with pytest.raises(UserLookupUnavailableError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.factory.assert_not_called()


def test_unknown_class_is_rejected_after_gateway_check(setup) -> None:
    """Достоверный ученик не заменяет проверку существования класса."""
    setup.uow.classes.get_class_by_id.return_value = None
    with pytest.raises(ClassNotFoundError):
        asyncio.run(setup.handler.handle(setup.command))
    assert setup.operations[0] == "gateway"
    setup.uow.class_periods.create_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("student_id", str(STUDENT)),
        ("student_id", None),
        ("class_id", 0),
        ("class_id", -1),
        ("class_id", 2**31),
        ("class_id", True),
        ("class_id", "10"),
        ("actor_id", ""),
        ("actor_id", "0"),
        ("actor_id", "-1"),
        ("actor_id", "042"),
        ("actor_id", " 42"),
        ("actor_id", "٤٢"),
        ("actor_id", str(2**63)),
        ("actor_id", 42),
        ("request_id", ""),
        ("request_id", "not-a-uuid"),
        ("request_id", uuid4()),
    ],
)
def test_invalid_command_is_rejected_at_creation(setup, field, value) -> None:
    """Неверные данные не позволяют создать команду для обработчика."""
    data = setup.command.model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        AddStudentToClassCommand(**data)


def test_command_accepts_valid_upper_bounds() -> None:
    """Верхние допустимые значения не должны ошибочно отклоняться."""
    command = AddStudentToClassCommand(
        student_id=STUDENT,
        class_id=2147483647,
        actor_id="9223372036854775807",
        request_id=REQUEST_ID,
    )
    assert command.class_id == 2147483647
    assert command.actor_id == "9223372036854775807"


@pytest.mark.parametrize("failure_at", ["outbox", "exit"])
def test_write_or_commit_failure_does_not_return_success(setup, failure_at) -> None:
    """Сбой записи/выхода UoW не должен быть скрыт результатом created=True."""
    failure = RuntimeError("database unavailable")
    if failure_at == "outbox":
        setup.uow.outbox.add_event.side_effect = failure
    else:
        setup.uow.__aexit__.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(setup.handler.handle(setup.command))
    assert caught.value is failure


@pytest.mark.parametrize("winner_class", [10, 20, None])
def test_concurrent_conflict_reads_winner_only_after_failed_uow_exits(
    setup, winner_class
) -> None:
    """Проверяет новый UoW, no-op только для того же класса и отсутствие retry."""
    setup.uow.class_periods.create_period.side_effect = CurrentPeriodAlreadyExistsError
    recovery = Mock()
    winner = (
        StudentClassPeriod(STUDENT, winner_class, id=456, joined_at=JOINED_AT)
        if winner_class is not None
        else None
    )
    recovery.class_periods.get_current_period_for_student = AsyncMock(
        return_value=winner
    )

    async def enter_recovery():
        assert setup.operations == ["gateway", "enter", "exit"]
        return recovery

    recovery.__aenter__ = AsyncMock(side_effect=enter_recovery)
    recovery.__aexit__ = AsyncMock(return_value=None)
    setup.factory.side_effect = [setup.uow, recovery]
    if winner_class == 10:
        result = asyncio.run(setup.handler.handle(setup.command))
        assert result.created is False
        assert result.period.id == 456
        assert result.period.class_id == 10
    else:
        with pytest.raises(StudentClassConflictError):
            asyncio.run(setup.handler.handle(setup.command))
    recovery.class_periods.get_current_period_for_student.assert_awaited_once_with(
        STUDENT
    )
    setup.uow.class_periods.create_period.assert_awaited_once()
    setup.uow.outbox.add_event.assert_not_awaited()
    assert setup.factory.call_count == 2


def test_unrelated_insert_failure_is_not_recovered_as_existing_period(setup) -> None:
    """Не маскирует произвольный сбой сохранения успешным повтором."""
    setup.uow.class_periods.create_period.side_effect = RuntimeError("storage failed")
    with pytest.raises(RuntimeError, match="storage failed"):
        asyncio.run(setup.handler.handle(setup.command))
    assert setup.factory.call_count == 1
