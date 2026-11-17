"""Использует общий UUID пользователя Gateway, сохраняя уроки и outbox.

Revision ID: d7a8046e2b91
Revises: c9c13a8d994d
"""

import os
from pathlib import Path

from alembic import op

from schedule_service.infrastructure.teacher_id_migration import load_teacher_id_mapping
from schedule_service.infrastructure.teacher_uuid_schema import (
    downgrade_teacher_ids,
    upgrade_teacher_ids,
)

revision = "d7a8046e2b91"
down_revision = "c9c13a8d994d"
branch_labels = None
depends_on = None


def _mapping():
    path = os.environ.get("SCHEDULE_TEACHER_ID_MAP_FILE")
    return load_teacher_id_mapping(Path(path)) if path else {}


def upgrade() -> None:
    """Переносит старые ссылки только при полном подтверждённом соответствии."""
    upgrade_teacher_ids(op.get_bind(), _mapping())


def downgrade() -> None:
    """Возвращает старые ID, если известны все обратные соответствия."""
    downgrade_teacher_ids(op.get_bind(), _mapping())
