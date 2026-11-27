from datetime import UTC, datetime
from typing import Self

import pytest

from schedule_service.application.ports.outbox_repository import PendingOutboxEvent


def _event(event_id: int, lesson_id: int) -> PendingOutboxEvent:
    return PendingOutboxEvent(
        id=event_id,
        event_type="lesson.snapshot",
        payload={"lesson_id": lesson_id},
        created_at=datetime(2026, 9, 13, 10, tzinfo=UTC),
    )


class FakeOutboxRepository:
    def __init__(self, events: list[PendingOutboxEvent], pending: int = 0) -> None:
        self._events = events
        self._pending = pending
        self.marked_published: list[list[int]] = []
        self.count_pending_calls = 0

    async def get_pending(self, *, limit: int) -> list[PendingOutboxEvent]:
        self.last_limit = limit
        return self._events[:limit]

    async def mark_published(self, *, event_ids: list[int]) -> None:
        self.marked_published.append(event_ids)

    async def count_pending(self) -> int:
        self.count_pending_calls += 1
        return self._pending


class FakeUnitOfWork:
    def __init__(self, outbox: FakeOutboxRepository) -> None:
        self.outbox = outbox
        self.closed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.closed = True


class FakePublisher:
    def __init__(self, read_uow: FakeUnitOfWork) -> None:
        self._read_uow = read_uow
        self.published: list[int] = []
        self.batches: list[list[PendingOutboxEvent]] = []

    async def publish(self, event: PendingOutboxEvent) -> None:
        assert self._read_uow.closed
        self.published.append(event.id)

    async def publish_many(self, events: list[PendingOutboxEvent]) -> None:
        assert self._read_uow.closed
        self.batches.append(list(events))
        self.published.extend(event.id for event in events)


@pytest.mark.anyio
async def test_relay_publishes_pending_events_after_read_uow_is_closed() -> None:
    from schedule_service.application.outbox_relay import OutboxRelay

    events = [_event(7, 501), _event(8, 502)]
    outbox = FakeOutboxRepository(events)
    read_uow = FakeUnitOfWork(outbox)
    uows = [read_uow, FakeUnitOfWork(outbox), FakeUnitOfWork(outbox)]
    publisher = FakePublisher(read_uow)
    relay = OutboxRelay(uow_factory=lambda: uows.pop(0), publisher=publisher)

    delivered = await relay.run_once()

    assert delivered == 2
    assert publisher.published == [7, 8]
    assert outbox.marked_published == [[7, 8]]


@pytest.mark.anyio
async def test_relay_does_not_mark_or_continue_after_publish_failure() -> None:
    from schedule_service.application.outbox_relay import OutboxRelay

    event = _event(7, 501)
    outbox = FakeOutboxRepository([event])
    read_uow = FakeUnitOfWork(outbox)

    class FailingPublisher(FakePublisher):
        async def publish_many(self, events: list[PendingOutboxEvent]) -> None:
            assert self._read_uow.closed
            self.published.extend(event.id for event in events)
            raise ConnectionError("Kafka is unavailable")

    publisher = FailingPublisher(read_uow)
    relay = OutboxRelay(uow_factory=lambda: read_uow, publisher=publisher)

    with pytest.raises(ConnectionError, match="Kafka is unavailable"):
        await relay.run_once()

    assert publisher.published == [7]
    assert outbox.marked_published == []
    assert outbox.count_pending_calls == 0


@pytest.mark.anyio
async def test_relay_publishes_one_batch_per_cycle_with_configured_limit() -> None:
    from schedule_service.application.outbox_relay import OutboxRelay

    events = [_event(i, 500 + i) for i in range(1, 6)]
    outbox = FakeOutboxRepository(events)
    read_uow = FakeUnitOfWork(outbox)
    uows = [read_uow, FakeUnitOfWork(outbox), FakeUnitOfWork(outbox)]
    publisher = FakePublisher(read_uow)
    relay = OutboxRelay(
        uow_factory=lambda: uows.pop(0), publisher=publisher, batch_size=500
    )

    delivered = await relay.run_once()

    assert outbox.last_limit == 500
    assert delivered == 5
    assert len(publisher.batches) == 1
    assert [event.id for event in publisher.batches[0]] == [1, 2, 3, 4, 5]


@pytest.mark.anyio
async def test_relay_logs_cycle_counters_and_survives_empty_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from schedule_service.application.outbox_relay import OutboxRelay

    events = [_event(7, 501), _event(8, 502)]
    outbox = FakeOutboxRepository(events, pending=3)
    read_uow = FakeUnitOfWork(outbox)
    uows = [read_uow, FakeUnitOfWork(outbox), FakeUnitOfWork(outbox)]
    relay = OutboxRelay(
        uow_factory=lambda: uows.pop(0), publisher=FakePublisher(read_uow)
    )

    with caplog.at_level(
        logging.INFO, logger="schedule_service.application.outbox_relay"
    ):
        delivered = await relay.run_once()

    assert delivered == 2
    assert outbox.count_pending_calls == 1
    assert "published 2 events, 3 pending" in caplog.text

    empty_outbox = FakeOutboxRepository([], pending=0)
    empty_read_uow = FakeUnitOfWork(empty_outbox)
    empty_uows = [empty_read_uow, FakeUnitOfWork(empty_outbox)]
    empty_relay = OutboxRelay(
        uow_factory=lambda: empty_uows.pop(0), publisher=FakePublisher(empty_read_uow)
    )

    with caplog.at_level(
        logging.INFO, logger="schedule_service.application.outbox_relay"
    ):
        delivered = await empty_relay.run_once()

    assert delivered == 0
    assert "published 0 events, 0 pending" in caplog.text
