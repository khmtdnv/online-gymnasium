"""Создаёт собственную таблицу домашних заданий Homework."""

import sqlalchemy as sa
from alembic import op

revision = "21c39bd05a74"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт таблицу с одним заданием на урок и одним способом срока."""
    op.create_table(
        "homework_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issued_lesson_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("due_lesson_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "issued_lesson_id", name="homework_assignments_issued_lesson_unique"
        ),
        sa.CheckConstraint(
            "(due_lesson_id IS NULL) <> (due_at IS NULL)",
            name="homework_assignments_one_due",
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 1 AND 10000 AND "
            r"description = btrim(description, U&'\0009\000A\000B\000C\000D"
            r"\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002"
            r"\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')",
            name="homework_assignments_description_valid",
        ),
        sa.CheckConstraint(
            "issued_lesson_id > 0 AND class_id > 0 AND subject_id > 0 AND (due_lesson_id IS NULL OR due_lesson_id > 0)",
            name="homework_assignments_positive_references",
        ),
    )


def downgrade() -> None:
    """Удаляет только таблицу Homework; данные удаляются вместе с ней."""
    op.drop_table("homework_assignments")
