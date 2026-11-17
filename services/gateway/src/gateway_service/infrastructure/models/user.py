from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from gateway_service.infrastructure.models.base import Base


class UserRow(Base):
    """Строка пользователя Gateway с уникальным email и допустимой ролью."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default=""
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "first_name ~ '[^[:space:]]' AND first_name = btrim(first_name)",
            name="users_first_name_nonblank",
        ),
        CheckConstraint(
            "last_name ~ '[^[:space:]]' AND last_name = btrim(last_name)",
            name="users_last_name_nonblank",
        ),
        CheckConstraint(
            "role IN ('student', 'teacher', 'parent', 'admin')",
            name="users_valid_role",
        ),
        UniqueConstraint("email", name="users_email_unique"),
    )
