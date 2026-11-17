from schedule_service.application.ports.event_publisher import EventPublisher
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory


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
        """Публикует одну пачку событий и отмечает отправку каждого.

        При сбое между отправкой и commit событие может быть опубликовано повторно.

        Returns:
            Количество опубликованных событий.
        """
        async with self._uow_factory() as uow:
            events = await uow.outbox.get_pending(limit=self._batch_size)

        for event in events:
            await self._publisher.publish(event)

            async with self._uow_factory() as uow:
                await uow.outbox.mark_published(event_id=event.id)

        return len(events)
