"""Собственный inbox и личные уведомления, без внешних FK к Users."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Метаданные отдельных миграций Notifications."""


class NotificationEventRow(Base):
    """Маркер идемпотентности и отпечаток обработанного события."""

    __tablename__ = "notification_events"
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))


class NotificationRow(Base):
    """Событие может создать записи для ученика и плательщика без дубля одной пары."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "recipient_id", name="notification_event_recipient_unique"
        ),
        Index("notification_recipient_history", "recipient_id", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("notification_events.event_id"))
    recipient_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    link: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
