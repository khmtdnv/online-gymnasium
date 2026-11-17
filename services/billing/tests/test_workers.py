"""Неподтверждённая доставка Kafka не должна скрывать событие из outbox."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiokafka.errors import KafkaError

from billing_service import workers


@pytest.mark.parametrize("fails", [True, False])
def test_relay_marks_only_after_ack_and_closes_producer(monkeypatch, fails):
    event_id = uuid4()
    envelope = {"event_id": str(event_id), "payload": {"student_id": str(uuid4())}}
    store = SimpleNamespace(
        pending_events=AsyncMock(return_value=[envelope]), mark_published=AsyncMock()
    )
    producer = SimpleNamespace(
        start=AsyncMock(),
        stop=AsyncMock(),
        send_and_wait=AsyncMock(side_effect=KafkaError() if fails else None),
    )
    monkeypatch.setattr(workers, "BillingStore", lambda sessions: store)
    monkeypatch.setattr(workers, "AIOKafkaProducer", lambda **kwargs: producer)

    async def stop_after_batch(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(workers.asyncio, "sleep", stop_after_batch)

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await workers.relay(
                SimpleNamespace(
                    kafka_bootstrap_servers="test:9092", platform_events_topic="test"
                ),
                None,
            )
        assert producer.stop.await_count == 1
        if fails:
            store.mark_published.assert_not_awaited()
        else:
            store.mark_published.assert_awaited_once_with(event_id)

    asyncio.run(run())
