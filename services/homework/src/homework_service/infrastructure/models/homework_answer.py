"""Попытки сдачи; ограничения сохраняют историю при конкурентных запросах."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column

from homework_service.infrastructure.models.base import Base


class HomeworkAnswerRow(Base):
    """Один сданный ответ с однократным результатом проверки."""

    __tablename__ = "homework_answers"
    __table_args__ = (
        UniqueConstraint(
            "homework_id",
            "student_id",
            "attempt_number",
            name="homework_answers_attempt_unique",
        ),
        UniqueConstraint(
            "homework_id",
            "student_id",
            "idempotency_key",
            name="homework_answers_key_unique",
        ),
        Index(
            "homework_answers_submitted_unique",
            "homework_id",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),
        Index("homework_answers_homework_idx", "homework_id", "submitted_at", "id"),
        CheckConstraint(
            "attempt_number > 0 AND char_length(answer_text) <= 10000",
            name="homework_answers_text_valid",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[!-~]{1,128}$' AND request_hash ~ '^[0-9a-f]{64}$'",
            name="homework_answers_request_valid",
        ),
        CheckConstraint(
            "char_length(teacher_comment) <= 10000",
            name="homework_answers_comment_valid",
        ),
        CheckConstraint(
            "(status = 'submitted' AND grade IS NULL AND reviewer_id IS NULL AND reviewed_at IS NULL AND teacher_comment = '') OR "
            "(status = 'returned' AND grade IS NULL AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL AND char_length(btrim(teacher_comment)) > 0) OR "
            "(status = 'graded' AND grade BETWEEN 2 AND 5 AND grade IS NOT NULL AND reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="homework_answers_review_valid",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    homework_id: Mapped[int] = mapped_column(
        ForeignKey("homework_assignments.id", name="homework_answers_homework_fkey"),
        nullable=False,
    )
    student_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    answer_text: Mapped[str] = mapped_column(String(10000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="submitted"
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    grade: Mapped[int | None] = mapped_column(Integer)
    teacher_comment: Mapped[str] = mapped_column(
        String(10000), nullable=False, server_default=""
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
