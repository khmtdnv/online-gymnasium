import asyncio
import json
from uuid import UUID

from aiokafka import AIOKafkaProducer

from schedule_service.application.ports.outbox_repository import PendingOutboxEvent


class KafkaEventPublisher:
    """Передаёт событие в Kafka с ID урока в качестве ключа сообщения."""

    def __init__(
        self,
        producer: AIOKafkaProducer,
        topic: str,
        snapshot_topic: str = "schedule.lessons.v2",
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            producer: Клиент Kafka для отправки сообщений.
            topic: Название Kafka-топика для публикации.
            snapshot_topic: Отдельный поток снимков с UUID преподавателя.
        """
        self._producer = producer
        self._topic = topic
        self._snapshot_topic = snapshot_topic

    def _render(self, event: PendingOutboxEvent) -> tuple[str, bytes, bytes]:
        """Builds the destination topic, encoded envelope and message key."""
        envelope = {
            "event_id": event.id,
            "event_type": event.event_type,
            "occurred_at": event.created_at.isoformat(),
            "payload": event.payload,
        }
        topic = self._topic
        if event.event_type == "lesson.snapshot":
            teacher_id = event.payload.get("teacher_id")
            if not isinstance(teacher_id, str):
                raise ValueError("Snapshot teacher_id must be a UUID string")
            UUID(teacher_id)
            envelope["schema_version"] = 2
            topic = self._snapshot_topic

        return (
            topic,
            json.dumps(envelope, separators=(",", ":")).encode(),
            str(event.payload["lesson_id"]).encode(),
        )

    async def publish(self, event: PendingOutboxEvent) -> None:
        """Отправляет событие в Kafka и ждёт подтверждения брокера.

        Args:
            event: Событие с данными для обработки или отправки.
        """
        topic, value, key = self._render(event)
        await self._producer.send_and_wait(topic, value, key=key)

    async def publish_many(self, events: list[PendingOutboxEvent]) -> None:
        """Sends a batch of events, then waits for all broker acks.

        Every send is scheduled without waiting for its confirmation, then
        acknowledgements of all sends are collected. On any failure the first
        error is raised, so callers must not mark the events published and the
        at-least-once guarantee holds.

        Args:
            events: Events of a single batch to publish to Kafka.
        """
        messages = [self._render(event) for event in events]
        futures = []
        for topic, value, key in messages:
            futures.append(await self._producer.send(topic, value, key=key))

        results = await asyncio.gather(*futures, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
