"""Отправка сохранённых событий с допустимым повтором после сбоя."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from homework_service.application.ports.unit_of_work import UnitOfWork


class OutboxRelay:
    """Не удерживает SQL-транзакцию во время ожидания Kafka."""

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
        """Читает пачку, ждёт подтверждения каждой отправки и затем отмечает её.

        Returns:
            Число подтверждённых отправок.

        Raises:
            Exception: Ошибка БД или Kafka; неподтверждённая строка остаётся в очереди.
        """
        async with self._uow_factory() as uow:
            events = await uow.outbox.get_pending(limit=self._batch_size)
        for event in events:
            await self._publish(event)
            async with self._uow_factory() as uow:
                await uow.outbox.mark_published(UUID(event["event_id"]))
        return len(events)
