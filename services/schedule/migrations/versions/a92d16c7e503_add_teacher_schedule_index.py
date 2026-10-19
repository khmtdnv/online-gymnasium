"""Добавляет индекс чтения расписания преподавателя без изменения уроков."""

from alembic import op

revision = "a92d16c7e503"
down_revision = "d7a8046e2b91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Индексирует преподавателя, время начала и ID урока."""
    op.create_index(
        "scheduled_lessons_teacher_starts_id_idx",
        "scheduled_lessons",
        ["teacher_id", "starts_at", "id"],
    )


def downgrade() -> None:
    """Удаляет только индекс, сохраняя уроки."""
    op.drop_index(
        "scheduled_lessons_teacher_starts_id_idx", table_name="scheduled_lessons"
    )
