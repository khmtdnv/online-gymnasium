"""Добавляет очередь событий, не изменяя существующие оценки и задания."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a41e72c6d930"
down_revision = "2fffe60b890e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт пустой outbox; прошлые проверки не выдаёт за новые события."""
    op.create_table(
        "homework_event_outbox",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "homework_outbox_pending",
        "homework_event_outbox",
        ["created_at", "event_id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    """Удаляет только outbox; перед откатом необходимо обработать его очередь."""
    op.drop_index("homework_outbox_pending", table_name="homework_event_outbox")
    op.drop_table("homework_event_outbox")
