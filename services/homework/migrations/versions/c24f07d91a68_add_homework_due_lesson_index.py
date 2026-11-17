"""Индексирует задания к уроку, не изменяя сохранённые данные."""

from alembic import op

revision = "c24f07d91a68"
down_revision = "e13c8bd4a902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет индекс для первой группы карточки."""
    op.create_index(
        "homework_assignments_due_lesson_idx", "homework_assignments", ["due_lesson_id"]
    )


def downgrade() -> None:
    """Удаляет только индекс, оставляя задания нетронутыми."""
    op.drop_index(
        "homework_assignments_due_lesson_idx", table_name="homework_assignments"
    )
