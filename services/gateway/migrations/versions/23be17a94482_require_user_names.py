"""Запрещает пустые имя и фамилию после заполнения существующих пользователей."""

import sqlalchemy as sa
from alembic import op

revision = "23be17a94482"
down_revision = "713f086d09a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Убирает пустые значения по умолчанию и добавляет проверки содержимого.

    Notes:
        Если старые данные ещё пусты, PostgreSQL отклонит миграцию целиком.
        ФИО исправляются до запуска, а не выдумываются внутри миграции.
    """
    for name in ("first_name", "last_name"):
        op.alter_column(
            "users", name, existing_type=sa.String(100), server_default=None
        )
        op.create_check_constraint(
            f"users_{name}_nonblank",
            "users",
            f"{name} ~ '[^[:space:]]' AND {name} = btrim({name})",
        )


def downgrade() -> None:
    """Снимает обязательность непустого значения, не изменяя сохранённые имена."""
    for name in ("last_name", "first_name"):
        op.drop_constraint(f"users_{name}_nonblank", "users", type_="check")
        op.alter_column("users", name, existing_type=sa.String(100), server_default="")
