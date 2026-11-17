"""Неподтверждённая Kafka отправка остаётся в outbox для следующего запуска."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest


def test_relay_closes_read_transaction_and_marks_only_acknowledged_event():
    from homework_service.application.outbox_relay import OutboxRelay

    active = False
    marks = []
    sends = []
    events = [
        {"event_id": str(UUID(int=i)), "payload": {"student_id": str(UUID(int=3))}}
        for i in (1, 2)
    ]

    async def pending(limit):
        assert active and limit == 100
        return events

    async def mark(event_id):
        assert active
        marks.append(event_id)

    @asynccontextmanager
    async def uow():
        nonlocal active
        active = True
        try:
            yield SimpleNamespace(
                outbox=SimpleNamespace(get_pending=pending, mark_published=mark)
            )
        finally:
            active = False

    async def publish(event):
        assert not active
        sends.append(event["event_id"])
        if len(sends) == 2:
            raise RuntimeError("broker unavailable")

    async def run():
        with pytest.raises(RuntimeError, match="broker unavailable"):
            await OutboxRelay(uow, publish).run_once()
        assert marks == [UUID(int=1)]
        assert len(sends) == 2

    asyncio.run(run())


def test_worker_closes_producer_and_database_on_cancel(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from homework_service.workers import outbox_relay as worker

    engine = SimpleNamespace(dispose=AsyncMock())
    producer = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    relay = SimpleNamespace(run_once=AsyncMock(side_effect=asyncio.CancelledError))
    monkeypatch.setattr(
        worker,
        "RelaySettings",
        lambda: SimpleNamespace(
            database_url="unused",
            kafka_bootstrap_servers="unused",
            platform_events_topic="platform.events.v1",
            batch_size=100,
        ),
    )
    monkeypatch.setattr(worker, "create_engine", lambda _: engine)
    monkeypatch.setattr(worker, "create_session_factory", Mock())
    monkeypatch.setattr(worker, "AIOKafkaProducer", Mock(return_value=producer))
    monkeypatch.setattr(worker, "OutboxRelay", Mock(return_value=relay))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run())
    producer.stop.assert_awaited_once()
    engine.dispose.assert_awaited_once()
