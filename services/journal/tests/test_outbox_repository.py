"""Проверяет JSON-контракт события и отсутствие самостоятельного commit."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def test_outbox_saves_exact_envelope_without_commit() -> None:
    """Ловит потерю actor/серверных полей, неверную дату и лишний commit."""
    from journal_service.application.events import StudentAddedToClassEvent
    from journal_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = Mock(spec=AsyncSession)
    rows = []
    session.add.side_effect = rows.append
    event = StudentAddedToClassEvent(
        event_id=UUID("aaaaaaaa-0000-4000-8000-000000000001"),
        occurred_at=datetime(2026, 10, 14, 17, tzinfo=timezone(timedelta(hours=5))),
        request_id="bbbbbbbb-0000-4000-8000-000000000002",
        actor_id="42",
        student_id=UUID("cccccccc-0000-4000-8000-000000000003"),
        period_id=123,
        class_id=10,
    )
    asyncio.run(SqlAlchemyOutboxRepository(session).add_event(event))
    assert len(rows) == 1
    row = rows[0]
    assert row.event_id == event.event_id
    assert row.published_at is None
    assert row.envelope == {
        "event_id": "aaaaaaaa-0000-4000-8000-000000000001",
        "event_source": "journal",
        "event_type": "journal.student_class.changed",
        "schema_version": 1,
        "occurred_at": "2026-10-14T12:00:00Z",
        "request_id": "bbbbbbbb-0000-4000-8000-000000000002",
        "actor": {"source": "backoffice", "id": "42"},
        "payload": {
            "operation": "added",
            "student_id": "cccccccc-0000-4000-8000-000000000003",
            "previous": None,
            "current": {"period_id": 123, "class_id": 10},
        },
    }
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize("operation", ["transferred", "removed"])
def test_outbox_serializes_period_change_previous_and_current(operation: str) -> None:
    """Не теряет исходный период и не выдаёт завершение за добавление."""
    from datetime import UTC
    from uuid import uuid4

    from journal_service.application import events
    from journal_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    student = uuid4()
    fields = {
        "event_id": uuid4(),
        "occurred_at": datetime(2026, 10, 16, 12, tzinfo=UTC),
        "request_id": str(uuid4()),
        "actor_id": "42",
        "student_id": student,
    }
    if operation == "transferred":
        event = events.StudentTransferredToClassEvent(
            **fields,
            previous_period_id=10,
            previous_class_id=1,
            period_id=11,
            class_id=2,
        )
        current = {"period_id": 11, "class_id": 2}
    else:
        event = events.StudentClassPeriodEndedEvent(**fields, period_id=10, class_id=1)
        current = None
    session = Mock(spec=AsyncSession)
    rows = []
    session.add.side_effect = rows.append
    asyncio.run(SqlAlchemyOutboxRepository(session).add_event(event))
    assert len(rows) == 1
    assert rows[0].envelope == {
        "event_id": str(fields["event_id"]),
        "event_source": "journal",
        "event_type": "journal.student_class.changed",
        "schema_version": 1,
        "occurred_at": "2026-10-16T12:00:00Z",
        "request_id": fields["request_id"],
        "actor": {"source": "backoffice", "id": "42"},
        "payload": {
            "operation": operation,
            "student_id": str(student),
            "previous": {"period_id": 10, "class_id": 1},
            "current": current,
        },
    }
    session.commit.assert_not_called()


def test_outbox_propagates_flush_failure() -> None:
    """Сбой события должен дойти до UoW, а не превратиться в успех."""
    from datetime import UTC
    from uuid import uuid4

    from journal_service.application.events import StudentAddedToClassEvent
    from journal_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = Mock(spec=AsyncSession)
    failure = RuntimeError("write failed")
    session.flush = AsyncMock(side_effect=failure)
    event = StudentAddedToClassEvent(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC),
        request_id=str(uuid4()),
        actor_id="42",
        student_id=uuid4(),
        period_id=1,
        class_id=1,
    )
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(SqlAlchemyOutboxRepository(session).add_event(event))
    assert caught.value is failure
    session.commit.assert_not_called()
