"""События портала отдельно от очереди задач Celery."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from document_service.infrastructure.models.base import Base


class DocumentEventRow(Base):
    """Готовность документа и Kafka-событие фиксируются одной транзакцией."""

    __tablename__ = "document_event_outbox"
    __table_args__ = (
        Index(
            "document_events_pending",
            "created_at",
            "event_id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    envelope: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
