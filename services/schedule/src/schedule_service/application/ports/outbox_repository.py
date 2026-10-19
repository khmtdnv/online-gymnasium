from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from schedule_service.domain.events import LessonSnapshot, ScheduleChanged


class PendingOutboxEvent(BaseModel):
    """Непубликованное событие из outbox с данными для Kafka."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: int
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class OutboxRepository(Protocol):
    """Контракт записи событий и отметки их публикации."""

    async def add(
        self,
        event: ScheduleChanged | LessonSnapshot,
    ) -> None:
        """Записывает событие изменения расписания или снимок урока в outbox.

        Args:
            event: Событие с данными для обработки или отправки.

        Raises:
            TypeError: Тип события не поддерживается.
        """
        ...

    async def get_pending(self, *, limit: int) -> list[PendingOutboxEvent]:
        """Читает ограниченную пачку ещё не опубликованных записей outbox.

        Args:
            limit: Максимальное число записей в пачке.

        Returns:
            Непубликованные записи, не больше указанного limit.
        """
        ...

    async def mark_published(self, *, event_id: int) -> None:
        """Ставит время публикации записи outbox в текущей транзакции.

        Args:
            event_id: ID события outbox.
        """
        ...
