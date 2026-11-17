"""Создаёт страницы и упорядоченные пачки координат учеников."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "pen_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Добавляет собственные таблицы, не изменяя чужие сервисы."""
    op.create_table(
        "pen_pages",
        sa.Column("lesson_id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Uuid(), primary_key=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "lesson_id > 0 AND last_sequence BETWEEN 0 AND 4096 AND point_count BETWEEN 0 AND 20000",
            name="pen_page_limits",
        ),
    )
    op.create_table(
        "pen_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("batch_id", name="pen_batch_identity"),
        sa.UniqueConstraint(
            "lesson_id", "student_id", "sequence", name="pen_page_sequence"
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id", "student_id"], ["pen_pages.lesson_id", "pen_pages.student_id"]
        ),
        sa.CheckConstraint(
            "sequence BETWEEN 1 AND 4096", name="pen_batch_sequence_positive"
        ),
    )


def downgrade():
    """Удаляет данные Pen только при явно запрошенном откате этой ревизии."""
    op.drop_table("pen_batches")
    op.drop_table("pen_pages")
