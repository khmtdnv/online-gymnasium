"""Добавляет ожидаемые вложения без изменения существующих заданий.

Revision ID: 488c14e7f719
Revises: c24f07d91a68
"""

import sqlalchemy as sa
from alembic import op

revision = "488c14e7f719"
down_revision = "c24f07d91a68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт метаданные файлов и локальные ограничения готовности."""
    op.create_table(
        "homework_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("homework_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "upload_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.CheckConstraint(
            "(upload_status = 'pending' AND storage_key IS NULL) OR (upload_status = 'ready' AND storage_key IS NOT NULL AND char_length(storage_key) > 0)",
            name="homework_files_state_valid",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="homework_files_digest_valid"
        ),
        sa.CheckConstraint(
            "char_length(content_type) BETWEEN 1 AND 127",
            name="homework_files_type_valid",
        ),
        sa.CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 255", name="homework_files_name_valid"
        ),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 10485760", name="homework_files_size_valid"
        ),
        sa.ForeignKeyConstraint(
            ["homework_id"],
            ["homework_assignments.id"],
            name="homework_files_homework_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "homework_files_homework_idx", "homework_files", ["homework_id"], unique=False
    )


def downgrade() -> None:
    """Удаляет метаданные вложений, сохраняя сами домашние задания."""
    op.drop_index("homework_files_homework_idx", table_name="homework_files")
    op.drop_table("homework_files")
