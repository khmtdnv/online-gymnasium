from typing import Protocol

from schedule_service.application.ports.outbox_repository import PendingOutboxEvent


class EventPublisher(Protocol):
    """Контракт отправки события из outbox во внешний брокер."""

    async def publish(self, event: PendingOutboxEvent) -> None:
        """Отправляет событие в Kafka и ждёт подтверждения брокера.

        Args:
            event: Событие с данными для обработки или отправки.
        """
        ...

    async def publish_many(self, events: list[PendingOutboxEvent]) -> None:
        """Publishes a batch of events and waits for every broker ack.

        Sends all events without waiting for each confirmation, then collects
        acknowledgements of all sends. On any partial failure raises without
        marking the batch published, so the at-least-once guarantee holds.

        Args:
            events: Events to publish as a single batch.
        """
        ...
