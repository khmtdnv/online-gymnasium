"""Добавляет названия предметов, сохраняя ID существующих уроков."""

import sqlalchemy as sa
from alembic import op

revision = "b31e6a97d204"
down_revision = "a92d16c7e503"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт справочник; неизвестные названия остаются NULL, а не догадкой."""
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id > 0", name="subjects_positive_id"),
        sa.CheckConstraint(
            "name IS NULL OR (char_length(name) BETWEEN 1 AND 100 AND name = btrim(name, E' \\t\\n\\r'))",
            name="subjects_valid_name",
        ),
    )
    op.execute(
        "INSERT INTO subjects(id) SELECT DISTINCT subject_id FROM scheduled_lessons WHERE subject_id > 0"
    )


def downgrade() -> None:
    """Удаляет только справочник, не затрагивая уроки и прежние subject_id."""
    op.drop_table("subjects")
