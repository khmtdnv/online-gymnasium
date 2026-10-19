"""Текущее закрепление преподавателей, без отдельной истории периодов."""

from uuid import UUID

from sqlalchemy import ForeignKey, Integer, PrimaryKeyConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from journal_service.infrastructure.models.base import Base


class TeacherClassRow(Base):
    """Одна уникальная пара пользователя Gateway и класса Journal."""

    __tablename__ = "teacher_classes"

    teacher_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("teacher_id", "class_id", name="teacher_classes_pkey"),
    )
