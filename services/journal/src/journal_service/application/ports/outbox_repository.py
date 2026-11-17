"""Контракт сохранения события в транзакции изменения класса."""

from typing import Protocol
from uuid import UUID

from journal_service.application.events import StudentClassChangedEvent


class OutboxRepository(Protocol):
    """Сохраняет намерение отправить событие; сам ничего не публикует."""

    async def add_event(self, event: StudentClassChangedEvent) -> None:
        """Записывает событие без самостоятельного завершения транзакции.

        Args:
            event: Событие добавления, перевода или завершения с серверной датой.
        """
        ...

    async def get_pending(self, *, limit: int) -> list[dict]:
        """Читает пачку ожидающих событий для relay."""
        ...

    async def mark_published(self, event_id: UUID) -> None:
        """Записывает подтверждение брокера в текущей транзакции."""
        ...
