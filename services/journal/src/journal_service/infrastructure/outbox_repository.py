"""Запись события Journal в той же транзакции, что и период ученика."""

from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.application.events import (
    StudentClassChangedEvent,
    StudentClassPeriodEndedEvent,
    StudentTransferredToClassEvent,
)
from journal_service.infrastructure.models.outbox_event import JournalOutboxEventRow


class SqlAlchemyOutboxRepository:
    """Сериализует событие, но не делает commit и не отправляет его в Kafka."""

    def __init__(self, session: AsyncSession) -> None:
        """Получает общую сессию Unit of Work.

        Args:
            session: Сессия, в которой сохраняется период ученика.
        """
        self._session = session

    async def add_event(self, event: StudentClassChangedEvent) -> None:
        """Сохраняет JSON-контракт события до завершения общей транзакции.

        Args:
            event: Данные добавления, перевода или завершения с серверным временем.

        Raises:
            ValueError: Дата события не содержит часового пояса.
            SQLAlchemyError: Запись не удалась; ошибка передаётся владельцу UoW.
        """
        if event.occurred_at.utcoffset() is None:
            raise ValueError("Event occurred_at must be timezone-aware")
        occurred_at = (
            event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        )
        current = {"period_id": event.period_id, "class_id": event.class_id}
        previous = None
        operation = "added"
        if isinstance(event, StudentTransferredToClassEvent):
            operation = "transferred"
            previous = {
                "period_id": event.previous_period_id,
                "class_id": event.previous_class_id,
            }
        elif isinstance(event, StudentClassPeriodEndedEvent):
            operation = "removed"
            previous, current = current, None
        row = JournalOutboxEventRow(
            event_id=event.event_id,
            envelope={
                "event_id": str(event.event_id),
                "event_source": "journal",
                "event_type": "journal.student_class.changed",
                "schema_version": 1,
                "occurred_at": occurred_at,
                "request_id": event.request_id,
                "actor": {"source": "backoffice", "id": event.actor_id},
                "payload": {
                    "operation": operation,
                    "student_id": str(event.student_id),
                    "previous": previous,
                    "current": current,
                },
            },
        )
        self._session.add(row)
        await self._session.flush()
