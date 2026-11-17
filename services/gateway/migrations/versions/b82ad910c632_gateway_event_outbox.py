"""Добавляет очередь аудита Gateway без переноса паролей или старых сессий."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b82ad910c632"
down_revision = "23be17a94482"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт пустой outbox для новых успешных действий."""
    op.create_table(
        "gateway_event_outbox",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "gateway_outbox_pending",
        "gateway_event_outbox",
        ["created_at", "event_id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    """Удаляет только очередь; перед откатом её необходимо обработать."""
    op.drop_table("gateway_event_outbox")
