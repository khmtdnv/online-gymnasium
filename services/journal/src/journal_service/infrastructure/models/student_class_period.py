from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import Mapped, mapped_column

from journal_service.infrastructure.models.base import Base


class StudentClassPeriodRow(Base):
    """Хранит период принадлежности ученика классу, включая завершённую историю."""

    __tablename__ = "student_class_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[UUID] = mapped_column(PSQL_UUID(as_uuid=True), nullable=False)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )

    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "student_class_periods_current_student_unique",
            "student_id",
            unique=True,
            postgresql_where=left_at.is_(None),
        ),
        CheckConstraint(
            "left_at IS NULL or left_at >= joined_at",
            name="student_class_periods_valid_period",
        ),
    )
