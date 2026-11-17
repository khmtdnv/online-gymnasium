"""Только собственные заказы/попытки Billing; нет копий Users и карточных данных."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Метаданные отдельных миграций Billing."""


class TuitionOrderRow(Base):
    """Один серверный счёт на ученика и месяц, с неизменной суммой."""

    __tablename__ = "tuition_orders"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "study_month",
            "period_type",
            name="tuition_order_student_month",
        ),
        CheckConstraint(
            "amount_kopecks BETWEEN 100 AND 100000000 AND EXTRACT(DAY FROM study_month) = 1",
            name="tuition_order_values",
        ),
        CheckConstraint(
            "status IN ('unpaid', 'paid', 'refunded')", name="tuition_order_status"
        ),
        CheckConstraint(
            "period_type IN ('month', 'quarter')", name="tuition_order_period_type"
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[UUID] = mapped_column(Uuid)
    study_month: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(10), server_default="month")
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="unpaid")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaymentRow(Base):
    """Постоянный provider_key переживает сеть и перезапуск процесса."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("payer_id", "request_key", name="payment_request_key"),
        Index("payment_order_history", "order_id", "id"),
        UniqueConstraint("provider_key", name="payment_provider_key"),
        UniqueConstraint("provider_id", name="payment_provider_identity"),
        CheckConstraint(
            "status IN ('creating','pending','succeeded','canceled','unknown','manual_review','refunded')",
            name="payment_status",
        ),
        Index(
            "payment_active_order",
            "order_id",
            unique=True,
            postgresql_where=text(
                "status IN ('creating','pending','unknown','manual_review','succeeded')"
            ),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("tuition_orders.id"))
    payer_id: Mapped[UUID] = mapped_column(Uuid)
    request_key: Mapped[UUID] = mapped_column(Uuid)
    provider_key: Mapped[UUID] = mapped_column(Uuid)
    provider_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="creating")
    confirmation_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefundRow(Base):
    """Одна полная попытка возврата; первый ключ не заменяется новым при сбое."""

    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("payment_id", name="refund_payment_unique"),
        UniqueConstraint("actor_id", "request_key", name="refund_request_key"),
        UniqueConstraint("provider_key", name="refund_provider_key"),
        UniqueConstraint("provider_id", name="refund_provider_identity"),
        CheckConstraint(
            "status IN ('creating','pending','succeeded','canceled','unknown','manual_review')",
            name="refund_status",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    request_key: Mapped[UUID] = mapped_column(Uuid)
    provider_key: Mapped[UUID] = mapped_column(Uuid)
    provider_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="creating")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BillingEventRow(Base):
    """Изменение финансового статуса и его событие фиксируются вместе."""

    __tablename__ = "billing_event_outbox"
    __table_args__ = (
        Index(
            "billing_outbox_pending",
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
