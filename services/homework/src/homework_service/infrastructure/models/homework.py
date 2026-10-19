"""Одна строка соответствует одному общему ДЗ урока."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from homework_service.infrastructure.models.base import Base


class HomeworkRow(Base):
    """Хранит задание без SQL-связей с чужими базами данных."""

    __tablename__ = "homework_assignments"
    __table_args__ = (
        Index("homework_assignments_due_lesson_idx", "due_lesson_id"),
        Index(
            "homework_assignments_class_created_id_idx",
            "class_id",
            desc("created_at"),
            desc("id"),
        ),
        UniqueConstraint(
            "issued_lesson_id", name="homework_assignments_issued_lesson_unique"
        ),
        CheckConstraint(
            "(due_lesson_id IS NULL) <> (manual_due_datetime IS NULL)",
            name="homework_assignments_one_due",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issued_lesson_id: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint(
            "issued_lesson_id > 0", name="homework_assignments_issued_lesson_positive"
        ),
        nullable=False,
    )
    class_id: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("class_id > 0", name="homework_assignments_class_positive"),
        nullable=False,
    )
    subject_id: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("subject_id > 0", name="homework_assignments_subject_positive"),
        nullable=False,
    )
    author_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        CheckConstraint(
            # Полный набор whitespace Python3.14 str.strip(), не только ASCII space.
            "char_length(description) BETWEEN 1 AND 10000 AND "
            r"description = btrim(description, U&'\0009\000A\000B\000C\000D"
            r"\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
            r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')",
            name="homework_assignments_description_valid",
        ),
        nullable=False,
    )
    due_lesson_id: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            "due_lesson_id > 0", name="homework_assignments_due_lesson_positive"
        ),
        nullable=True,
    )
    manual_due_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
