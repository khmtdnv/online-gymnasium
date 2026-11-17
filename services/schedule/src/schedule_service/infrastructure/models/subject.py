"""Справочник названий, принадлежащий сервису расписания."""

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from schedule_service.infrastructure.models.base import Base


class SubjectRow(Base):
    """Сохраняет старые ID; отсутствующее название не подменяет догадкой."""

    __tablename__ = "subjects"
    __table_args__ = (
        CheckConstraint("id > 0", name="subjects_positive_id"),
        CheckConstraint(
            "name IS NULL OR (char_length(name) BETWEEN 1 AND 100 AND name = btrim(name, E' \\t\\n\\r'))",
            name="subjects_valid_name",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
