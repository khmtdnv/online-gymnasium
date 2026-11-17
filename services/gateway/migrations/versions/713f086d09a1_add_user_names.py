"""Добавляет ФИО; старые пользователи остаются без выдуманных имён."""

import sqlalchemy as sa
from alembic import op

revision = "713f086d09a1"
down_revision = "da179cfd6aef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет необязательные части имени без потери существующих пользователей."""
    for name in ("first_name", "last_name", "middle_name"):
        op.add_column(
            "users", sa.Column(name, sa.String(100), nullable=False, server_default="")
        )


def downgrade() -> None:
    """Удаляет поля ФИО; значения этих полей при откате теряются."""
    for name in ("middle_name", "last_name", "first_name"):
        op.drop_column("users", name)
