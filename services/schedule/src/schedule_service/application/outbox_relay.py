import logging

from schedule_service.application.ports.event_publisher import EventPublisher
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory

logger = logging.getLogger(__name__)


class OutboxRelay:
    """Публикует события PostgreSQL в Kafka и затем отмечает отправку."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        publisher: EventPublisher,
        batch_size: int = 100,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            publisher: Клиент отправки сообщений во внешний брокер.
            batch_size: Максимальное число записей для одной итерации отправки.
        """
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size

    async def run_once(self) -> int:
        """Публикация одной пачки событий и отметка её одной командой.

        Пачка отправляется целиком через publish_many, подтверждённые события
        отмечаются одной UPDATE-командой, после чего пишется информационный
        лог счётчиков цикла. При сбое между отправкой и отметкой событие может
        быть опубликовано повторно (at-least-once).

        Returns:
            Количество опубликованных событий.
        """
        async with self._uow_factory() as uow:
            events = await uow.outbox.get_pending(limit=self._batch_size)

        published = len(events)
        if events:
            await self._publisher.publish_many(events)

            async with self._uow_factory() as uow:
                await uow.outbox.mark_published(
                    event_ids=[event.id for event in events]
                )

        async with self._uow_factory() as uow:
            pending = await uow.outbox.count_pending()

        logger.info("Outbox relay published %d events, %d pending", published, pending)
        return published
