"""При ошибке ClickHouse или DLQ consumer не пропускает исходную пачку."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from aiokafka.structs import TopicPartition
from test_audit_events import review_event


@pytest.mark.parametrize("failure", [None, "storage", "dlq"])
def test_batch_commits_only_after_storage_and_dlq(failure):
    from analytics_service.workers.audit import process_batch

    partition = TopicPartition("platform.events.v1", 0)
    messages = [
        SimpleNamespace(topic=partition.topic, partition=0, offset=i, value=value)
        for i, value in enumerate([json.dumps(review_event()).encode(), b"{}"])
    ]
    order = []

    async def save(events):
        assert events[0].payload["grade"] == 4
        order.append("storage")
        if failure == "storage":
            raise RuntimeError("CH unavailable")

    async def send(*args, **kwargs):
        order.append("dlq")
        if failure == "dlq":
            raise RuntimeError("DLQ unavailable")

    async def commit(offsets):
        assert offsets == {partition: 2}
        order.append("commit")

    async def run():
        task = process_batch(
            {partition: messages},
            SimpleNamespace(add_many=save),
            SimpleNamespace(send_and_wait=send),
            SimpleNamespace(commit=commit),
            dlq_topic="audit.dlq",
            schedule_topic="schedule.lessons.v2",
        )
        if failure:
            with pytest.raises(RuntimeError):
                await task
        else:
            await task

    asyncio.run(run())
    assert (
        order
        == {
            None: ["storage", "dlq", "commit"],
            "storage": ["storage"],
            "dlq": ["storage", "dlq"],
        }[failure]
    )
