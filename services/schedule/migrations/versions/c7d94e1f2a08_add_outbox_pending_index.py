"""Add a partial index for unpublished outbox events."""

import sqlalchemy as sa
from alembic import op

revision = "c7d94e1f2a08"
down_revision = "b31e6a97d204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Indexes only unpublished events to keep relay batch reads cheap."""
    op.create_index(
        "outbox_events_published_at_idx",
        "outbox_events",
        ["published_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    """Drops only the partial index, keeping all events."""
    op.drop_index("outbox_events_published_at_idx", table_name="outbox_events")
