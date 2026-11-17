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
