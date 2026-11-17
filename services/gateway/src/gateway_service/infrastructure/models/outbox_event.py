"""События Gateway в той же базе, что пользователи и refresh-сессии."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gateway_service.infrastructure.models.base import Base


class GatewayOutboxEventRow(Base):
    __tablename__ = "gateway_event_outbox"
    __table_args__ = (
        Index(
            "gateway_outbox_pending",
            "created_at",
            "event_id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
