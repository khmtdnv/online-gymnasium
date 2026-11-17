"""Уточняет имя ручной даты сдачи без изменения значений.

Revision ID: e13c8bd4a902
Revises: b7c81d9e42af
"""

from alembic import op

revision = "e13c8bd4a902"
down_revision = "b7c81d9e42af"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Переименовывает колонку, сохраняя даты и ограничение способа срока."""
    op.alter_column(
        "homework_assignments", "due_at", new_column_name="manual_due_datetime"
    )


def downgrade() -> None:
    """Возвращает прежнее имя без потери дат или заданий."""
    op.alter_column(
        "homework_assignments", "manual_due_datetime", new_column_name="due_at"
    )
