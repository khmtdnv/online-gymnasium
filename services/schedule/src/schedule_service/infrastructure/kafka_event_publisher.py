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

    async def publish(self, event: PendingOutboxEvent) -> None:
        """Отправляет событие в Kafka и ждёт подтверждения брокера.

        Args:
            event: Событие с данными для обработки или отправки.
        """
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

        await self._producer.send_and_wait(
            topic,
            json.dumps(envelope, separators=(",", ":")).encode(),
            key=str(event.payload["lesson_id"]).encode(),
        )
