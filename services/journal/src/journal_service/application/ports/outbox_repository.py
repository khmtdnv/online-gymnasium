"""Контракт сохранения события в транзакции изменения класса."""

from typing import Protocol

from journal_service.application.events import StudentClassChangedEvent


class OutboxRepository(Protocol):
    """Сохраняет намерение отправить событие; сам ничего не публикует."""

    async def add_event(self, event: StudentClassChangedEvent) -> None:
        """Записывает событие без самостоятельного завершения транзакции.

        Args:
            event: Событие добавления, перевода или завершения с серверной датой.
        """
        ...
