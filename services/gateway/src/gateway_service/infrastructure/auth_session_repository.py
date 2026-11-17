from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_service.infrastructure.models.auth_session import AuthSessionRow


class AuthSessionRepository:
    """Работает с серверными сессиями в транзакции вызывающего кода."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию базы без открытия новой транзакции."""
        self._session = session

    async def create(
        self, session_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        """Добавляет новую серверную сессию; commit выполняет вызывающий код."""
        self._session.add(
            AuthSessionRow(id=session_id, user_id=user_id, expires_at=expires_at)
        )

    async def is_active(self, session_id: UUID, user_id: UUID) -> bool:
        """Проверяет владельца, срок действия и отсутствие отзыва."""
        stmt = select(AuthSessionRow.id).where(
            AuthSessionRow.id == session_id,
            AuthSessionRow.user_id == user_id,
            AuthSessionRow.revoked_at.is_(None),
            AuthSessionRow.expires_at > func.now(),
        )
        return await self._session.scalar(stmt) is not None

    async def revoke(self, session_id: UUID, user_id: UUID) -> None:
        """Идемпотентно отзывает принадлежащую пользователю сессию."""
        stmt = (
            update(AuthSessionRow)
            .where(
                AuthSessionRow.id == session_id,
                AuthSessionRow.user_id == user_id,
                AuthSessionRow.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        await self._session.execute(stmt)
