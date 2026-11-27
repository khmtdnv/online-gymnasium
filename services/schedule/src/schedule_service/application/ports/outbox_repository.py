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

    async def mark_published(self, *, event_ids: list[int]) -> None:
        """Marks the given outbox events published with a single statement.

        Args:
            event_ids: IDs of outbox events confirmed by the broker; an empty
                list is a no-op.
        """
        ...

    async def count_pending(self) -> int:
        """Counts outbox events that are not published yet.

        Returns:
            Number of rows with published_at IS NULL.
        """
        ...

    async def delete_published_before(self, *, cutoff: datetime) -> int:
        """Deletes published outbox events older than the cutoff.

        Idempotency keys are never deleted: only rows with published_at set
        are removed.

        Args:
            cutoff: Exclusive upper bound for published_at.

        Returns:
            Number of deleted rows.
        """
        ...
