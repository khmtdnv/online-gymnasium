"""Различает прежние месячные и будущие четвертные счета.

Revision ID: 7f9a20c4d518
Revises: c2106ec0880e
"""

import sqlalchemy as sa
from alembic import op

revision = "7f9a20c4d518"
down_revision = "c2106ec0880e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Помечает существующие счета месячными без изменения их платежей."""
    op.add_column(
        "tuition_orders",
        sa.Column("period_type", sa.String(10), nullable=False, server_default="month"),
    )
    op.create_check_constraint(
        "tuition_order_period_type",
        "tuition_orders",
        "period_type IN ('month', 'quarter')",
    )
    op.drop_constraint("tuition_order_student_month", "tuition_orders", type_="unique")
    op.create_unique_constraint(
        "tuition_order_student_month",
        "tuition_orders",
        ["student_id", "study_month", "period_type"],
    )


def downgrade() -> None:
    """Не удаляет признак четверти, если такие счета уже существуют."""
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM tuition_orders WHERE period_type = 'quarter')"
        )
    ).scalar_one():
        raise RuntimeError("Quarterly orders must be migrated before downgrade")
    op.drop_constraint("tuition_order_student_month", "tuition_orders", type_="unique")
    op.create_unique_constraint(
        "tuition_order_student_month", "tuition_orders", ["student_id", "study_month"]
    )
    op.drop_constraint("tuition_order_period_type", "tuition_orders", type_="check")
    op.drop_column("tuition_orders", "period_type")
