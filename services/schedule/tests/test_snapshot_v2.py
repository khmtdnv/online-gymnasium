"""Разделяет UUID-снимки и прежний поток инвалидации кеша."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from schedule_service.application.ports.outbox_repository import PendingOutboxEvent


def test_snapshot_routes_to_v2_but_invalidation_keeps_old_topic():
    from schedule_service.infrastructure.kafka_event_publisher import (
        KafkaEventPublisher,
    )

    producer = AsyncMock()
    publisher = KafkaEventPublisher(producer, topic="old", snapshot_topic="new")
    for event_type in ("lesson.snapshot", "schedule.changed"):
        asyncio.run(
            publisher.publish(
                PendingOutboxEvent(
                    id=42,
                    event_type=event_type,
                    payload={
                        "lesson_id": 501,
                        "teacher_id": "8df96b7a-7d30-44e7-b577-f6581300e101",
                    },
                    created_at=datetime(2026, 10, 16, tzinfo=UTC),
                )
            )
        )
    calls = producer.send_and_wait.call_args_list
    assert [call.args[0] for call in calls] == ["new", "old"]
    assert json.loads(calls[0].args[1])["schema_version"] == 2
    assert calls[0].kwargs["key"] == b"501"
