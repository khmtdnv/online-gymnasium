"""Переименовывает таблицу периодов ученика без удаления её данных.

Revision ID: 44fda21bc443
Revises: f98bb7a9333b
Create Date: 2026-10-13 17:29:39.895274

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "44fda21bc443"
down_revision: str | Sequence[str] | None = "f98bb7a9333b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Переименовывает таблицу, индекс, ограничения и последовательность ID."""
    op.rename_table("class_memberships", "student_class_periods")
    op.execute(
        "ALTER INDEX class_memberships_current_student_unique "
        "RENAME TO student_class_periods_current_student_unique"
    )
    op.execute(
        "ALTER TABLE student_class_periods "
        "RENAME CONSTRAINT class_memberships_valid_period "
        "TO student_class_periods_valid_period"
    )
    op.execute(
        "ALTER TABLE student_class_periods "
        "RENAME CONSTRAINT class_memberships_pkey "
        "TO student_class_periods_pkey"
    )
    op.execute(
        "ALTER TABLE student_class_periods "
        "RENAME CONSTRAINT class_memberships_class_id_fkey "
        "TO student_class_periods_class_id_fkey"
    )
    op.execute(
        "ALTER SEQUENCE class_memberships_id_seq RENAME TO student_class_periods_id_seq"
    )


def downgrade() -> None:
    """Возвращает прежние имена объектам БД, сохраняя данные и счётчик ID."""
    op.execute(
        "ALTER SEQUENCE student_class_periods_id_seq RENAME TO class_memberships_id_seq"
    )
    op.execute(
        "ALTER TABLE student_class_periods "
        "RENAME CONSTRAINT student_class_periods_class_id_fkey "
        "TO class_memberships_class_id_fkey"
    )
    op.execute(
        "ALTER TABLE student_class_periods "
        "RENAME CONSTRAINT student_class_periods_pkey "
        "TO class_memberships_pkey"
    )
    op.execute(
        "ALTER TABLE student_class_periods "
        "RENAME CONSTRAINT student_class_periods_valid_period "
        "TO class_memberships_valid_period"
    )
    op.execute(
        "ALTER INDEX student_class_periods_current_student_unique "
        "RENAME TO class_memberships_current_student_unique"
    )
    op.rename_table("student_class_periods", "class_memberships")
