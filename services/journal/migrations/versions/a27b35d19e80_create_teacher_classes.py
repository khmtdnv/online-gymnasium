"""Создаёт текущие назначения преподавателей классам.

Revision ID: a27b35d19e80
Revises: d79431f0c9b2
"""

import sqlalchemy as sa
from alembic import op

revision = "a27b35d19e80"
down_revision = "d79431f0c9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет таблицу, не меняя существующих пользователей и классы."""
    op.create_table(
        "teacher_classes",
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.PrimaryKeyConstraint("teacher_id", "class_id", name="teacher_classes_pkey"),
    )


def downgrade() -> None:
    """Удаляет только назначения преподавателей; живое применение согласуется отдельно."""
    op.drop_table("teacher_classes")
