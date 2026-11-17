"""Commit не должен обгонять БД или подтверждение DLQ; сырой пакет не публикуется."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


def test_worker_keeps_offset_on_database_failure_and_sanitizes_dlq():
    from notifications_service.workers import process_batch

    envelope = {
        "event_id": str(uuid4()),
        "event_source": "documents",
        "event_type": "documents.document.completed",
        "schema_version": 1,
        "occurred_at": "2026-10-22T12:00:00Z",
        "request_id": None,
        "actor": {"source": "system", "id": "documents"},
        "payload": {
            "job_id": str(uuid4()),
            "creator_id": str(uuid4()),
            "document_type": "contract",
        },
    }
    message = SimpleNamespace(
        value=json.dumps(envelope).encode(), topic="test", partition=0, offset=7
    )
    fetched = {"partition": [message]}
    consumer = SimpleNamespace(commit=AsyncMock())
    sent = []
    fail_dlq = False

    async def send(topic, value, **kwargs):
        if fail_dlq:
            raise OSError("No DLQ ACK")
        sent.append(json.loads(value))

    producer = SimpleNamespace(send_and_wait=send)
    store = SimpleNamespace(record=AsyncMock(side_effect=OSError("DB down")))

    async def run():
        nonlocal fail_dlq
        with pytest.raises(OSError):
            await process_batch(
                fetched, store, producer, consumer, dlq_topic="test-dlq"
            )
        consumer.commit.assert_not_awaited()
        message.value = json.dumps(
            envelope
            | {"payload": envelope["payload"] | {"student_full_name": "must-not-leak"}}
        ).encode()
        fail_dlq = True
        with pytest.raises(OSError):
            await process_batch(
                fetched, store, producer, consumer, dlq_topic="test-dlq"
            )
        consumer.commit.assert_not_awaited()
        fail_dlq = False
        await process_batch(fetched, store, producer, consumer, dlq_topic="test-dlq")
        consumer.commit.assert_awaited_once()
        assert len(sent) == 1 and len(sent[0]["digest"]) == 64
        assert "must-not-leak" not in json.dumps(sent)
        assert set(sent[0]) == {"digest", "topic", "partition", "offset", "reason"}

    asyncio.run(run())
