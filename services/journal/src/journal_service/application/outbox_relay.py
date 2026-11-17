"""Публикация сохранённых событий Journal без распределённой транзакции."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from journal_service.application.ports.unit_of_work import UnitOfWork


class OutboxRelay:
    """После сбоя допускает повтор события с прежним event_id."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publish: Callable[[dict], Awaitable[None]],
        batch_size: int = 100,
    ) -> None:
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("Invalid outbox batch size")
        self._uow_factory, self._publish, self._batch_size = (
            uow_factory,
            publish,
            batch_size,
        )

    async def run_once(self) -> int:
        """Отмечает отправку только после Kafka ack, без SQL во время сети.

        Returns:
            Число подтверждённых событий.

        Raises:
            Exception: Kafka или БД недоступны; следующая итерация повторит событие.
        """
        async with self._uow_factory() as uow:
            events = await uow.outbox.get_pending(limit=self._batch_size)
        for event in events:
            await self._publish(event)
            async with self._uow_factory() as uow:
                await uow.outbox.mark_published(UUID(event["event_id"]))
        return len(events)
