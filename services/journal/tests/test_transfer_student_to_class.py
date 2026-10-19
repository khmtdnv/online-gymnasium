"""Учебные проверки перевода; handle намеренно остаётся работой ученика."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from journal_service.application.class_periods import ClassPeriodResult
from journal_service.application.events import StudentTransferredToClassEvent
from journal_service.application.ports import errors
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod

STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
REQUEST_ID = "bbbbbbbb-0000-4000-8000-000000000002"
JOINED_AT = datetime(2026, 9, 1, 9, tzinfo=UTC)
BOUNDARY = datetime(2026, 10, 16, 12, tzinfo=UTC)


def command_data():
    """Даёт независимые валидные входные данные для проверки ограничений."""
    return {
        "student_id": STUDENT,
        "target_class_id": 2,
        "expected_period_id": 10,
        "actor_id": "42",
        "request_id": REQUEST_ID,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("student_id", str(STUDENT)),
        ("student_id", None),
        ("target_class_id", 0),
        ("target_class_id", -1),
        ("target_class_id", True),
        ("target_class_id", "2"),
        ("target_class_id", 2**31),
        ("target_class_id", 1.0),
        ("expected_period_id", 0),
        ("expected_period_id", -1),
        ("expected_period_id", True),
        ("expected_period_id", "10"),
        ("expected_period_id", 2**31),
        ("expected_period_id", 1.0),
        ("actor_id", ""),
        ("actor_id", "0"),
        ("actor_id", "042"),
        ("actor_id", " 42"),
        ("actor_id", "٤٢"),
        ("actor_id", str(2**63)),
        ("actor_id", 42),
        ("request_id", "bad-uuid"),
        ("request_id", ""),
        ("request_id", uuid4()),
        ("unexpected", 123),
    ],
)
def test_command_rejects_invalid_data(field, value):
    """Неверные ID или доверенный контекст не доходят до handle."""
    from journal_service.application.transfer_student_to_class import (
        TransferStudentToClassCommand,
    )

    data = command_data()
    data[field] = value
    with pytest.raises(ValidationError):
        TransferStudentToClassCommand(**data)


def test_command_accepts_bounds_and_is_frozen():
    """Допустимые границы сохраняются; после проверки команду нельзя подменить."""
    from journal_service.application.transfer_student_to_class import (
        TransferStudentToClassCommand,
    )

    data = command_data()
    data.update(
        target_class_id=2147483647,
        expected_period_id=2147483647,
        actor_id="9223372036854775807",
    )
    command = TransferStudentToClassCommand(**data)
    assert command.target_class_id == 2147483647
    assert command.expected_period_id == 2147483647
    with pytest.raises(ValidationError):
        command.expected_period_id = 11


@pytest.fixture
def setup():
    """Подменяет внешние порты; последовательность записей остаётся наблюдаемой."""
    from journal_service.application.transfer_student_to_class import (
        TransferStudentToClassCommand,
        TransferStudentToClassHandler,
    )

    old = StudentClassPeriod(STUDENT, 1, id=10, joined_at=JOINED_AT)
    closed = StudentClassPeriod(
        STUDENT, 1, id=10, joined_at=JOINED_AT, left_at=BOUNDARY
    )
    saved = StudentClassPeriod(STUDENT, 2, id=11, joined_at=BOUNDARY)
    operations = []
    uow = Mock()
    uow.classes.get_class_by_id = AsyncMock(return_value=Class("7Б", 2026, id=2))
    uow.class_periods.get_period_for_update = AsyncMock(return_value=old)

    async def close_period(period_id):
        assert period_id == 10
        operations.append("close")
        return closed

    async def create_period(period):
        assert period == StudentClassPeriod(STUDENT, 2, joined_at=BOUNDARY)
        operations.append("create")
        return saved

    async def add_event(event):
        operations.append("event")

    async def enter():
        operations.append("enter")
        return uow

    async def exit_uow(*args):
        operations.append("exit")

    async def get_user(user_id):
        assert user_id == STUDENT
        operations.append("gateway")
        return GatewayUserInfo(id=STUDENT, role="student", is_active=True)

    uow.class_periods.close_period = AsyncMock(side_effect=close_period)
    uow.class_periods.create_period = AsyncMock(side_effect=create_period)
    uow.outbox.add_event = AsyncMock(side_effect=add_event)
    uow.__aenter__ = AsyncMock(side_effect=enter)
    uow.__aexit__ = AsyncMock(side_effect=exit_uow)
    reader = SimpleNamespace(get_user=AsyncMock(side_effect=get_user))
    factory = Mock(return_value=uow)
    return SimpleNamespace(
        old=old,
        closed=closed,
        saved=saved,
        uow=uow,
        reader=reader,
        factory=factory,
        operations=operations,
        command=TransferStudentToClassCommand(**command_data()),
        handler=TransferStudentToClassHandler(factory, reader),
    )


def assert_no_writes(setup):
    """Ошибочная команда не должна закрывать период, создавать строку или событие."""
    setup.uow.class_periods.close_period.assert_not_awaited()
    setup.uow.class_periods.create_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


def test_handle_transfers_with_common_boundary_and_one_event(setup):
    """Ловит потерю исходного ID, нарушение порядка записей и неверный аудит."""
    result = asyncio.run(setup.handler.handle(setup.command))
    assert isinstance(result, ClassPeriodResult)
    assert result.id == 11
    assert result.student_id == STUDENT
    assert result.class_id == 2
    assert result.joined_at == BOUNDARY
    assert result.left_at is None
    assert setup.operations == ["gateway", "enter", "close", "create", "event", "exit"]
    for method, names, expected in (
        (setup.uow.classes.get_class_by_id, ("class_id",), (2,)),
        (
            setup.uow.class_periods.get_period_for_update,
            ("student_id", "period_id"),
            (STUDENT, 10),
        ),
    ):
        method.assert_awaited_once()
        received = method.await_args
        values = received.args + tuple(
            received.kwargs[name] for name in names[len(received.args) :]
        )
        assert values == expected
    setup.uow.outbox.add_event.assert_awaited_once()
    supplied = setup.uow.outbox.add_event.await_args
    event = supplied.args[0] if supplied.args else supplied.kwargs["event"]
    assert isinstance(event, StudentTransferredToClassEvent)
    assert isinstance(event.event_id, UUID)
    assert event.occurred_at == BOUNDARY
    assert event.student_id == STUDENT
    assert event.previous_period_id == 10
    assert event.previous_class_id == 1
    assert event.period_id == 11
    assert event.class_id == 2
    assert event.actor_id == "42"
    assert event.request_id == REQUEST_ID


@pytest.mark.parametrize(
    "role, active",
    [("teacher", True), ("parent", True), ("admin", True), ("student", False)],
)
def test_handle_rejects_unfit_user_before_uow(setup, role, active):
    """Нельзя начать локальную запись для неактивного ученика или другой роли."""
    setup.reader.get_user.side_effect = None
    setup.reader.get_user.return_value = GatewayUserInfo(
        id=STUDENT, role=role, is_active=active
    )
    with pytest.raises(errors.InvalidStudentError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.factory.assert_not_called()
    assert_no_writes(setup)


def test_handle_rejects_missing_user_before_uow(setup):
    """Gateway 404 не превращается в новый период ученика."""
    setup.reader.get_user.side_effect = None
    setup.reader.get_user.return_value = None
    with pytest.raises(errors.StudentNotFoundError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.factory.assert_not_called()


def test_handle_propagates_unavailable_gateway_without_uow(setup):
    """Недоступность проверки не разрешает перевод."""
    setup.reader.get_user.side_effect = errors.UserLookupUnavailableError
    with pytest.raises(errors.UserLookupUnavailableError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.factory.assert_not_called()


def test_handle_rejects_unknown_target_without_writes(setup):
    """Существование ученика не заменяет проверку целевого класса."""
    setup.uow.classes.get_class_by_id.return_value = None
    with pytest.raises(errors.ClassNotFoundError):
        asyncio.run(setup.handler.handle(setup.command))
    assert setup.operations[0] == "gateway"
    assert_no_writes(setup)


@pytest.mark.parametrize("closed", [False, True])
def test_handle_rejects_missing_or_closed_expected_period(setup, closed):
    """Проверяет состояние периода; соответствие ID гарантирует репозиторий."""
    setup.uow.class_periods.get_period_for_update.return_value = (
        setup.closed if closed else None
    )
    with pytest.raises(errors.StudentClassPeriodConflictError):
        asyncio.run(setup.handler.handle(setup.command))
    assert_no_writes(setup)


def test_handle_same_class_is_noop_only_for_matching_open_period(setup):
    """Совпадение класса не должно создавать период и событие."""
    setup.uow.class_periods.get_period_for_update.return_value = StudentClassPeriod(
        STUDENT, 2, id=10, joined_at=JOINED_AT
    )
    result = asyncio.run(setup.handler.handle(setup.command))
    assert result.id == 10
    assert result.class_id == 2
    assert result.joined_at == JOINED_AT
    assert_no_writes(setup)


def test_handle_failed_close_is_conflict_without_new_period(setup):
    """Пустой результат условного UPDATE не позволяет продолжить перевод."""
    setup.uow.class_periods.close_period.side_effect = None
    setup.uow.class_periods.close_period.return_value = None
    with pytest.raises(errors.StudentClassPeriodConflictError):
        asyncio.run(setup.handler.handle(setup.command))
    setup.uow.class_periods.create_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


def test_handle_outbox_failure_reaches_uow(setup):
    """Сбой сохранения события не должен превращаться в успешный результат."""
    failure = RuntimeError("outbox unavailable")
    setup.uow.outbox.add_event.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(setup.handler.handle(setup.command))
    assert caught.value is failure
    assert setup.uow.__aexit__.await_args.args[1] is failure
