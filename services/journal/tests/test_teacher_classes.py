"""Правила назначения проверяются независимо от HTTP и SQLAlchemy."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from journal_service.application.ports.errors import (
    ClassNotFoundError,
    UserLookupUnavailableError,
)
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo

TEACHER = UUID("8df96b7a-7d30-44e7-b577-f6581300e101")


def setup(user=None, duplicate=False, missing_class=False):
    from journal_service.application.ports.errors import TeacherAlreadyAssignedError

    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.classes.get_class_by_id = AsyncMock(
        return_value=None if missing_class else object()
    )
    uow.teacher_classes.add = AsyncMock(
        side_effect=TeacherAlreadyAssignedError if duplicate else None
    )
    uow.teacher_classes.remove = AsyncMock(return_value=False)
    reader = SimpleNamespace(get_user=AsyncMock(return_value=user))
    return uow, reader


@pytest.mark.parametrize("duplicate", [False, True])
def test_assign_returns_creation_flag_and_checks_owner(duplicate):
    from journal_service.application.teacher_classes import (
        AssignTeacherToClassCommand,
        AssignTeacherToClassHandler,
    )

    uow, reader = setup(
        GatewayUserInfo(id=TEACHER, role="teacher", is_active=True), duplicate
    )
    result = asyncio.run(
        AssignTeacherToClassHandler(lambda: uow, reader).handle(
            AssignTeacherToClassCommand(teacher_id=TEACHER, class_id=7)
        )
    )
    assert result.created is not duplicate
    reader.get_user.assert_awaited_once_with(TEACHER)
    uow.teacher_classes.add.assert_awaited_once_with(TEACHER, 7)


@pytest.mark.parametrize(
    "role,active", [("student", True), ("admin", True), ("teacher", False)]
)
def test_non_active_teacher_rejected_before_writing(role, active):
    from journal_service.application.ports.errors import InvalidTeacherError
    from journal_service.application.teacher_classes import (
        AssignTeacherToClassCommand,
        AssignTeacherToClassHandler,
    )

    uow, reader = setup(GatewayUserInfo(id=TEACHER, role=role, is_active=active))
    with pytest.raises(InvalidTeacherError):
        asyncio.run(
            AssignTeacherToClassHandler(lambda: uow, reader).handle(
                AssignTeacherToClassCommand(teacher_id=TEACHER, class_id=7)
            )
        )
    uow.__aenter__.assert_not_awaited()


def test_missing_teacher_and_gateway_failure_are_not_success():
    from journal_service.application.ports.errors import TeacherNotFoundError
    from journal_service.application.teacher_classes import (
        AssignTeacherToClassCommand,
        AssignTeacherToClassHandler,
    )

    uow, reader = setup()
    handler = AssignTeacherToClassHandler(lambda: uow, reader)
    command = AssignTeacherToClassCommand(teacher_id=TEACHER, class_id=7)
    with pytest.raises(TeacherNotFoundError):
        asyncio.run(handler.handle(command))
    reader.get_user.side_effect = UserLookupUnavailableError
    with pytest.raises(UserLookupUnavailableError):
        asyncio.run(handler.handle(command))


def test_missing_class_is_not_created():
    from journal_service.application.teacher_classes import (
        AssignTeacherToClassCommand,
        AssignTeacherToClassHandler,
    )

    uow, reader = setup(
        GatewayUserInfo(id=TEACHER, role="teacher", is_active=True), missing_class=True
    )
    with pytest.raises(ClassNotFoundError):
        asyncio.run(
            AssignTeacherToClassHandler(lambda: uow, reader).handle(
                AssignTeacherToClassCommand(teacher_id=TEACHER, class_id=7)
            )
        )
    uow.teacher_classes.add.assert_not_awaited()


def test_unassign_does_not_depend_on_gateway_and_is_idempotent():
    from journal_service.application.teacher_classes import (
        UnassignTeacherFromClassCommand,
        UnassignTeacherFromClassHandler,
    )

    uow, _ = setup()
    command = UnassignTeacherFromClassCommand(teacher_id=TEACHER, class_id=7)
    handler = UnassignTeacherFromClassHandler(lambda: uow)
    assert asyncio.run(handler.handle(command)) is None
    assert asyncio.run(handler.handle(command)) is None
    assert uow.teacher_classes.remove.await_count == 2
