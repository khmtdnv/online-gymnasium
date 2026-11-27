import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from schedule_service.application.ports.outbox_repository import PendingOutboxEvent


def _snapshot_event(event_id: int, lesson_id: int) -> PendingOutboxEvent:
    return PendingOutboxEvent(
        id=event_id,
        event_type="lesson.snapshot",
        payload={
            "lesson_id": lesson_id,
            "teacher_id": "8df96b7a-7d30-44e7-b577-f6581300e101",
        },
        created_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
    )


def _changed_event(event_id: int, lesson_id: int) -> PendingOutboxEvent:
    return PendingOutboxEvent(
        id=event_id,
        event_type="schedule.changed",
        payload={"lesson_id": lesson_id, "class_id": 10, "affected_dates": []},
        created_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
    )


@pytest.mark.anyio
async def test_kafka_publisher_sends_documented_json_envelope_with_lesson_key() -> None:
    from schedule_service.infrastructure.kafka_event_publisher import (
        KafkaEventPublisher,
    )

    producer = AsyncMock(spec=AIOKafkaProducer)
    publisher = KafkaEventPublisher(producer=producer, topic="schedule.lessons")
    event = _snapshot_event(42, 501)

    await publisher.publish(event)

    call = producer.send_and_wait.await_args
    assert call.args[0] == "schedule.lessons.v2"
    assert json.loads(call.args[1]) == {
        "event_id": 42,
        "event_type": "lesson.snapshot",
        "schema_version": 2,
        "occurred_at": "2026-09-13T12:00:00+00:00",
        "payload": {
            "lesson_id": 501,
            "teacher_id": "8df96b7a-7d30-44e7-b577-f6581300e101",
        },
    }
    assert call.kwargs["key"] == b"501"


@pytest.mark.anyio
async def test_publish_many_sends_whole_batch_before_waiting_for_acks() -> None:
    from schedule_service.infrastructure.kafka_event_publisher import (
        KafkaEventPublisher,
    )

    producer = AsyncMock(spec=AIOKafkaProducer)
    loop = asyncio.get_running_loop()

    def _confirmed_future() -> asyncio.Future:
        future = loop.create_future()
        future.set_result(None)
        return future

    producer.send = AsyncMock(side_effect=lambda *_, **__: _confirmed_future())
    publisher = KafkaEventPublisher(producer=producer, topic="schedule.lessons")
    events = [_changed_event(41, 500), _snapshot_event(42, 501)]

    await publisher.publish_many(events)

    assert producer.send.await_count == 2
    first = producer.send.await_args_list[0]
    second = producer.send.await_args_list[1]
    assert first.args[0] == "schedule.lessons"
    assert json.loads(first.args[1]) == {
        "event_id": 41,
        "event_type": "schedule.changed",
        "occurred_at": "2026-09-13T12:00:00+00:00",
        "payload": {"lesson_id": 500, "class_id": 10, "affected_dates": []},
    }
    assert first.kwargs["key"] == b"500"
    assert second.args[0] == "schedule.lessons.v2"
    assert json.loads(second.args[1])["schema_version"] == 2
    assert second.kwargs["key"] == b"501"
    producer.send_and_wait.assert_not_awaited()


@pytest.mark.anyio
async def test_publish_many_accepts_empty_batch_without_sending() -> None:
    from schedule_service.infrastructure.kafka_event_publisher import (
        KafkaEventPublisher,
    )

    producer = AsyncMock(spec=AIOKafkaProducer)
    publisher = KafkaEventPublisher(producer=producer, topic="schedule.lessons")

    await publisher.publish_many([])

    producer.send.assert_not_awaited()
    producer.send_and_wait.assert_not_awaited()


@pytest.mark.anyio
async def test_publish_many_raises_on_partial_failure() -> None:
    from schedule_service.infrastructure.kafka_event_publisher import (
        KafkaEventPublisher,
    )

    producer = AsyncMock(spec=AIOKafkaProducer)
    loop = asyncio.get_running_loop()
    confirmed = loop.create_future()
    confirmed.set_result(None)
    failed = loop.create_future()
    failed.set_exception(KafkaError("broker timeout"))
    producer.send = AsyncMock(side_effect=[confirmed, failed])
    publisher = KafkaEventPublisher(producer=producer, topic="schedule.lessons")
    events = [_snapshot_event(41, 500), _snapshot_event(42, 501)]

    with pytest.raises(KafkaError):
        await publisher.publish_many(events)

    assert producer.send.await_count == 2


@pytest.mark.anyio
async def test_publish_many_validates_every_snapshot_teacher_id_upfront() -> None:
    from schedule_service.infrastructure.kafka_event_publisher import (
        KafkaEventPublisher,
    )

    producer = AsyncMock(spec=AIOKafkaProducer)
    publisher = KafkaEventPublisher(producer=producer, topic="schedule.lessons")
    broken = PendingOutboxEvent(
        id=43,
        event_type="lesson.snapshot",
        payload={"lesson_id": 502, "teacher_id": "not-a-uuid"},
        created_at=datetime(2026, 9, 13, 12, tzinfo=UTC),
    )

    with pytest.raises(ValueError):
        await publisher.publish_many([_snapshot_event(42, 501), broken])

    producer.send.assert_not_awaited()
