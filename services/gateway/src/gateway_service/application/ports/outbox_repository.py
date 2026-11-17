"""Транзакционные события пользователей и очередь доставки."""

from typing import Protocol
from uuid import UUID

from gateway_service.domain.user import User


class OutboxRepository(Protocol):
    async def add_user_event(self, event_type: str, user: User) -> None:
        """Записывает безопасный факт без завершения текущего UoW."""
        ...

    async def get_pending(self, *, limit: int) -> list[dict]:
        """Читает ограниченную пачку ожидающих конвертов."""
        ...

    async def mark_published(self, event_id: UUID) -> None:
        """Отмечает Kafka ack, не выполняя самостоятельный commit."""
        ...
