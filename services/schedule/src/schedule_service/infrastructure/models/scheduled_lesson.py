from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from schedule_service.infrastructure.models.base import Base


class ScheduledLessonRow(Base):
    """Строка урока с запретом пересечения плановых занятий класса и учителя."""

    __tablename__ = "scheduled_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    teacher_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="planned"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __table_args__ = (
        Index(
            "scheduled_lessons_teacher_starts_id_idx", "teacher_id", "starts_at", "id"
        ),
        CheckConstraint(
            "starts_at < ends_at",
            name="scheduled_lessons_valid_interval",
        ),
        ExcludeConstraint(
            ("class_id", "="),
            (func.tstzrange(starts_at, ends_at, "[)"), "&&"),
            where=text("status = 'planned'"),
            name="scheduled_lessons_no_class_overlap",
        ),
        ExcludeConstraint(
            ("teacher_id", "="),
            (func.tstzrange(starts_at, ends_at, "[)"), "&&"),
            where=text("status = 'planned'"),
            name="scheduled_lessons_no_teacher_overlap",
        ),
    )
