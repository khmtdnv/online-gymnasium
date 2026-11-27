from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession


def test_outbox_model_declares_partial_index_for_pending_events() -> None:
    from sqlalchemy.schema import CreateIndex

    from schedule_service.infrastructure.models.outbox_event import OutboxEventRow

    indexes = {index.name: index for index in OutboxEventRow.__table__.indexes}
    index = indexes["outbox_events_published_at_idx"]

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "CREATE INDEX outbox_events_published_at_idx" in ddl
    assert "ON outbox_events (published_at)" in ddl
    assert "WHERE published_at IS NULL" in ddl


@pytest.mark.anyio
async def test_repository_adds_schedule_changed_event_to_session() -> None:
    from schedule_service.domain.events import ScheduleChanged
    from schedule_service.infrastructure.models.outbox_event import OutboxEventRow
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemyOutboxRepository(session)

    await repository.add(
        ScheduleChanged(
            lesson_id=501,
            class_id=10,
            affected_dates=(date(2026, 9, 10), date(2026, 9, 11)),
        )
    )

    row = session.add.call_args.args[0]
    assert isinstance(row, OutboxEventRow)
    assert row.event_type == "schedule.changed"
    assert row.payload == {
        "lesson_id": 501,
        "class_id": 10,
        "affected_dates": ["2026-09-10", "2026-09-11"],
    }
    session.add.assert_called_once_with(row)


@pytest.mark.anyio
async def test_repository_adds_lesson_snapshot_event_to_session() -> None:
    from schedule_service.domain.events import LessonSnapshot
    from schedule_service.infrastructure.models.outbox_event import OutboxEventRow
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemyOutboxRepository(session)
    event = LessonSnapshot(
        lesson_id=501,
        class_id=10,
        teacher_id=UUID(int=100),
        subject_id=1000,
        starts_at=datetime(2026, 9, 13, 10, tzinfo=UTC),
        ends_at=datetime(2026, 9, 13, 11, tzinfo=UTC),
        status="planned",
        version=4,
    )

    await repository.add(event)

    row = session.add.call_args.args[0]
    assert isinstance(row, OutboxEventRow)
    assert row.event_type == "lesson.snapshot"
    assert row.payload == {
        "lesson_id": 501,
        "class_id": 10,
        "teacher_id": str(UUID(int=100)),
        "subject_id": 1000,
        "starts_at": "2026-09-13T10:00:00+00:00",
        "ends_at": "2026-09-13T11:00:00+00:00",
        "status": "planned",
        "version": 4,
    }
    session.add.assert_called_once_with(row)


@pytest.mark.anyio
async def test_repository_returns_pending_events_in_id_order() -> None:
    from schedule_service.infrastructure.models.outbox_event import OutboxEventRow
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    scalar_result = Mock()
    session.scalars.return_value = scalar_result
    scalar_result.all.return_value = [
        OutboxEventRow(
            id=7,
            event_type="lesson.snapshot",
            payload={"lesson_id": 501},
            created_at=datetime(2026, 9, 13, 10, tzinfo=UTC),
        ),
        OutboxEventRow(
            id=8,
            event_type="lesson.snapshot",
            payload={"lesson_id": 502},
            created_at=datetime(2026, 9, 13, 11, tzinfo=UTC),
        ),
    ]
    repository = SqlAlchemyOutboxRepository(session)

    events = await repository.get_pending(limit=100)

    assert [event.id for event in events] == [7, 8]
    assert events[0].event_type == "lesson.snapshot"
    assert events[0].payload == {"lesson_id": 501}
    assert events[0].created_at == datetime(2026, 9, 13, 10, tzinfo=UTC)
    session.scalars.assert_awaited_once()
    statement = session.scalars.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ORDER BY outbox_events.id" in sql


@pytest.mark.anyio
async def test_repository_marks_only_pending_events_as_published_in_one_update() -> (
    None
):
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemyOutboxRepository(session)

    await repository.mark_published(event_ids=[7, 8])

    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert sql.startswith("UPDATE outbox_events SET published_at=now()")
    assert "outbox_events.id IN (7, 8)" in sql
    assert "outbox_events.published_at IS NULL" in sql


@pytest.mark.anyio
async def test_repository_marks_empty_id_list_without_sql() -> None:
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemyOutboxRepository(session)

    await repository.mark_published(event_ids=[])

    session.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_repository_counts_only_pending_events() -> None:
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = 3
    repository = SqlAlchemyOutboxRepository(session)

    pending = await repository.count_pending()

    assert pending == 3
    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "count(*)" in sql
    assert "outbox_events.published_at IS NULL" in sql


@pytest.mark.anyio
async def test_repository_deletes_only_published_events_older_than_cutoff() -> None:
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )

    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value.rowcount = 4
    repository = SqlAlchemyOutboxRepository(session)

    deleted = await repository.delete_published_before(
        cutoff=datetime(2026, 11, 15, 12, tzinfo=UTC)
    )

    assert deleted == 4
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert sql.startswith("DELETE FROM outbox_events")
    assert "outbox_events.published_at IS NOT NULL" in sql
    assert "outbox_events.published_at < '2026-11-15 12:00:00+00:00'" in sql
    assert "idempotency" not in sql
