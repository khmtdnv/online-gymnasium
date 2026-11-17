"""Маркер события и все получатели фиксируются одной транзакцией PostgreSQL."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from notifications_service.contracts import (
    EventConflictError,
    Notification,
    TargetEvent,
    describe_event,
)
from notifications_service.models import NotificationEventRow, NotificationRow


class NotificationStore:
    """Короткие сессии чтения/записи, без Kafka внутри транзакции."""

    def __init__(self, sessions):
        self._sessions = sessions

    async def record(self, event: TargetEvent) -> bool:
        """Отличает повтор доставки от недопустимого переиспользования event_id.

        Args:
            event: Проверенный конверт поддерживаемого типа.

        Returns:
            True для новой записи, False для точного повтора.

        Raises:
            EventConflictError: Прежний ID события получил другое содержимое.
        """
        canonical = json.dumps(
            event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        async with self._sessions() as session, session.begin():
            try:
                async with session.begin_nested():
                    session.add(
                        NotificationEventRow(event_id=event.event_id, digest=digest)
                    )
                    await session.flush()
            except IntegrityError as exc:
                cause = (
                    getattr(exc.orig, "driver_exception", None) or exc.orig.__cause__
                )
                if (
                    getattr(cause, "constraint_name", None)
                    != "notification_events_pkey"
                ):
                    raise
                old = await session.get(NotificationEventRow, event.event_id)
                if old is None or old.digest != digest:
                    raise EventConflictError from exc
                return False
            recipients, title, body, link = describe_event(event)
            session.add_all(
                [
                    NotificationRow(
                        event_id=event.event_id,
                        recipient_id=user,
                        title=title,
                        body=body,
                        link=link,
                    )
                    for user in recipients
                ]
            )
        return True

    async def list_for(
        self, user_id: UUID, limit: int, offset: int
    ) -> list[Notification]:
        """Читает страницу только своего адресата, в порядке от новых к старым."""
        async with self._sessions() as session:
            rows = await session.scalars(
                select(NotificationRow)
                .where(NotificationRow.recipient_id == user_id)
                .order_by(NotificationRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [
                Notification.model_validate(row, from_attributes=True) for row in rows
            ]

    async def unread_count(self, user_id: UUID) -> int:
        """Считает непрочитанные записи указанного пользователя."""
        async with self._sessions() as session:
            return await session.scalar(
                select(func.count())
                .select_from(NotificationRow)
                .where(
                    NotificationRow.recipient_id == user_id,
                    NotificationRow.read_at.is_(None),
                )
            )

    async def mark_read(self, id_: int, user_id: UUID) -> bool:
        """Атомарно проверяет адресата и сохраняет время первого прочтения."""
        async with self._sessions() as session, session.begin():
            found = await session.scalar(
                update(NotificationRow)
                .where(
                    NotificationRow.id == id_, NotificationRow.recipient_id == user_id
                )
                .values(
                    read_at=func.coalesce(
                        NotificationRow.read_at, func.clock_timestamp()
                    )
                )
                .returning(NotificationRow.id)
            )
            return found is not None
