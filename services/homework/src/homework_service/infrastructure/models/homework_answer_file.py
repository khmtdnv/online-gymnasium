"""Файлы ответа отделены от общих вложений учителя."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from homework_service.infrastructure.models.base import Base


class HomeworkAnswerFileRow(Base):
    """Содержит только локальные метаданные, байты остаются в MinIO."""

    __tablename__ = "homework_answer_files"
    __table_args__ = (
        Index("homework_answer_files_answer_idx", "answer_id"),
        CheckConstraint(
            "size_bytes BETWEEN 1 AND 10485760", name="homework_answer_files_size_valid"
        ),
        CheckConstraint(
            "char_length(file_name) BETWEEN 1 AND 255 AND char_length(content_type) BETWEEN 1 AND 127",
            name="homework_answer_files_metadata_valid",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="homework_answer_files_digest_valid",
        ),
        CheckConstraint(
            "(upload_status = 'pending' AND storage_key IS NULL) OR (upload_status = 'ready' AND storage_key IS NOT NULL AND char_length(storage_key) > 0)",
            name="homework_answer_files_state_valid",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey(
            "homework_answers.id",
            name="homework_answer_files_answer_fkey",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    upload_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    storage_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, unique=True
    )
