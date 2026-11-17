"""Новый вид начислений не должен подменять прежние месячные счета."""

from billing_service.models import TuitionOrderRow


def test_order_distinguishes_quarterly_and_legacy_monthly_periods() -> None:
    table = TuitionOrderRow.__table__
    assert "period_type" in table.c
    assert table.c.period_type.nullable is False
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("student_id", "study_month", "period_type") in unique_columns
