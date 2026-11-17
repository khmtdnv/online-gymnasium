"""Добавляет индекс чтения класса без изменения заданий.

Revision ID: b7c81d9e42af
Revises: 93f52dc710ab
"""

import sqlalchemy as sa
from alembic import op

revision = "b7c81d9e42af"
down_revision = "93f52dc710ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ускоряет выборку класса в порядке страницы."""
    op.create_index(
        "homework_assignments_class_created_id_idx",
        "homework_assignments",
        ["class_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Убирает только индекс, не строки или столбцы заданий."""
    op.drop_index(
        "homework_assignments_class_created_id_idx", table_name="homework_assignments"
    )
