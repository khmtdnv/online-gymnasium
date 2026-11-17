"""Создаёт outbox событий Journal без изменения таблиц классов и периодов.

Revision ID: d79431f0c9b2
Revises: 44fda21bc443
Create Date: 2026-10-14 15:45:31.428127

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d79431f0c9b2"
down_revision: str | Sequence[str] | None = "44fda21bc443"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавляет очередь сохранённых, ещё не опубликованных событий."""
    from sqlalchemy.dialects import postgresql

    op.create_table(
        "journal_event_outbox",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    """Удаляет только outbox; сохранённые периоды остаются на месте."""
    op.drop_table("journal_event_outbox")
