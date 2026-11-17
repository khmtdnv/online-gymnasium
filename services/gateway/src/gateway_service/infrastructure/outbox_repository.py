"""Запись только факта входа/создания пользователя, без его credentials и ФИО."""

from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_service.domain.user import User
from gateway_service.infrastructure.models.outbox_event import GatewayOutboxEventRow


class SqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_user_event(self, event_type: str, user: User) -> None:
        """Связывает событие с текущей транзакцией, не отправляя его в сеть."""
        if event_type not in ("gateway.user.created", "gateway.user.logged_in"):
            raise ValueError("Unknown user event")
        moment = await self._session.scalar(select(func.clock_timestamp()))
        event_id = uuid4()
        actor = (
            {"source": "gateway", "id": str(user.id)}
            if event_type == "gateway.user.logged_in"
            else {"source": "service", "id": "backoffice"}
        )
        self._session.add(
            GatewayOutboxEventRow(
                event_id=event_id,
                envelope={
                    "event_id": str(event_id),
                    "event_source": "gateway",
                    "event_type": event_type,
                    "schema_version": 1,
                    "occurred_at": moment.isoformat(),
                    "request_id": None,
                    "actor": actor,
                    "payload": {"user_id": str(user.id), "role": user.role.value},
                },
            )
        )
        await self._session.flush()

    async def get_pending(self, *, limit: int) -> list[dict]:
        """Читает очередь, не блокируя SQL на время Kafka-вызова."""
        return list(
            await self._session.scalars(
                select(GatewayOutboxEventRow.envelope)
                .where(GatewayOutboxEventRow.published_at.is_(None))
                .order_by(
                    GatewayOutboxEventRow.created_at, GatewayOutboxEventRow.event_id
                )
                .limit(limit)
            )
        )

    async def mark_published(self, event_id: UUID) -> None:
        """Идемпотентно отмечает подтверждённую отправку."""
        await self._session.execute(
            update(GatewayOutboxEventRow)
            .where(
                GatewayOutboxEventRow.event_id == event_id,
                GatewayOutboxEventRow.published_at.is_(None),
            )
            .values(published_at=func.clock_timestamp())
        )
