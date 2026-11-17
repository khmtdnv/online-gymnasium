from datetime import datetime
from typing import Protocol
from uuid import UUID


class AuthSessionRepository(Protocol):
    """Хранение и проверка серверной сессии внутри транзакции."""

    async def create(
        self, session_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        """Создаёт сессию пользователя."""
        ...

    async def is_active(self, session_id: UUID, user_id: UUID) -> bool:
        """Проверяет, что сессия принадлежит пользователю и действует."""
        ...

    async def revoke(self, session_id: UUID, user_id: UUID) -> None:
        """Отзывает сессию пользователя."""
        ...
