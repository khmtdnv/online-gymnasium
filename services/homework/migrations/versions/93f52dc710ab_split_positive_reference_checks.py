"""Разделяет проверки ID по полям без изменения допустимых данных."""

from alembic import op

revision = "93f52dc710ab"
down_revision = "21c39bd05a74"
branch_labels = None
depends_on = None

TABLE = "homework_assignments"
POSITIVE_CHECKS = (
    ("homework_assignments_issued_lesson_positive", "issued_lesson_id > 0"),
    ("homework_assignments_class_positive", "class_id > 0"),
    ("homework_assignments_subject_positive", "subject_id > 0"),
    ("homework_assignments_due_lesson_positive", "due_lesson_id > 0"),
)


def upgrade() -> None:
    """Заменяет общий CHECK четырьмя именованными проверками полей."""
    op.drop_constraint("homework_assignments_positive_references", TABLE, type_="check")
    for name, condition in POSITIVE_CHECKS:
        op.create_check_constraint(name, TABLE, condition)


def downgrade() -> None:
    """Возвращает прежний общий CHECK, не удаляя строки и колонки."""
    for name, _ in POSITIVE_CHECKS:
        op.drop_constraint(name, TABLE, type_="check")
    op.create_check_constraint(
        "homework_assignments_positive_references",
        TABLE,
        "issued_lesson_id > 0 AND class_id > 0 AND subject_id > 0 AND "
        "(due_lesson_id IS NULL OR due_lesson_id > 0)",
    )
