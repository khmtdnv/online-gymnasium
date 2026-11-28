"""ORM-модели записей урока: посещаемость и оценки."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import Mapped, mapped_column

from journal_service.domain.lesson_records import AttendanceStatus, GradeKind
from journal_service.infrastructure.models.base import Base


def _enum_column(enum_class: type, name: str) -> SAEnum:
    """Создаёт колонку нативного PG-enum со значениями членов enum.

    Args:
        enum_class: Класс enum домена.
        name: Имя создаваемого типа в PostgreSQL.

    Returns:
        Тип колонки, хранящий значения (не имена) членов enum.
    """
    return SAEnum(
        enum_class,
        name=name,
        values_callable=lambda enumeration: [item.value for item in enumeration],
    )


class LessonAttendanceRow(Base):
    """Посещаемость урока: одна строка на (урок, ученик)."""

    __tablename__ = "lesson_attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lesson_date: Mapped[date] = mapped_column(Date, nullable=False)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    student_id: Mapped[UUID] = mapped_column(PSQL_UUID(as_uuid=True), nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        _enum_column(AttendanceStatus, "attendance_status"), nullable=False
    )
    generator: Mapped[bool] = mapped_column(
        Boolean, server_default=func.false(), nullable=False
    )
    author_id: Mapped[UUID] = mapped_column(PSQL_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "student_id", name="lesson_attendance_lesson_student_unique"
        ),
        Index("lesson_attendance_student_date", "student_id", "lesson_date"),
        Index("lesson_attendance_class_date", "class_id", "lesson_date"),
    )


class LessonGradeRow(Base):
    """Оценка за урок: одна строка на (урок, ученик, тип)."""

    __tablename__ = "lesson_grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lesson_date: Mapped[date] = mapped_column(Date, nullable=False)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    student_id: Mapped[UUID] = mapped_column(PSQL_UUID(as_uuid=True), nullable=False)
    grade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[GradeKind] = mapped_column(
        _enum_column(GradeKind, "grade_kind"), nullable=False
    )
    generator: Mapped[bool] = mapped_column(
        Boolean, server_default=func.false(), nullable=False
    )
    author_id: Mapped[UUID] = mapped_column(PSQL_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("grade BETWEEN 2 AND 5", name="lesson_grades_grade_range"),
        UniqueConstraint(
            "lesson_id",
            "student_id",
            "kind",
            name="lesson_grades_lesson_student_kind_unique",
        ),
        Index(
            "lesson_grades_student_subject_date",
            "student_id",
            "subject_id",
            "lesson_date",
        ),
    )
