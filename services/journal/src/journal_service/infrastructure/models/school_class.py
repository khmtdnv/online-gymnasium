from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from journal_service.infrastructure.models.base import Base


class ClassRow(Base):
    """Описывает хранение школьного класса в таблице classes."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(length=64), nullable=False)
    study_year: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("name", "study_year", name="classes_name_study_year_unique"),
        CheckConstraint(
            "study_year BETWEEN 1900 AND 9998", name="classes_valid_study_year"
        ),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 64 AND name = btrim(name)",
            name="classes_valid_name",
        ),
    )
