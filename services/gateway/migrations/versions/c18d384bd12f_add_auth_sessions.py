"""Добавляет хранение будущих серверных сессий без изменения текущего входа."""

import sqlalchemy as sa
from alembic import op

revision = "c18d384bd12f"
down_revision = "b82ad910c632"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт пустую таблицу сессий, сохраняя существующие токены."""
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Удаляет таблицу сессий при откате миграции."""
    op.drop_table("auth_sessions")
