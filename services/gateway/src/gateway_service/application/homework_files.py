"""Собственный контракт Gateway для ожидаемых вложений, без импорта Homework."""

import unicodedata
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".txt": "text/plain",
}


class HomeworkFileResult(BaseModel):
    """Проверенные публичные метаданные без приватного адреса объекта."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: int = Field(ge=1, le=2147483647)
    homework_id: int = Field(ge=1, le=2147483647)
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=10485760)
    content_type: str = Field(min_length=1, max_length=127)
    upload_status: Literal["pending", "ready"]

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """Не пропускает небезопасное название и несовместимый заявленный MIME.

        Returns:
            Проверенные метаданные.

        Raises:
            ValueError: Небезопасное имя либо несовместимый тип.
        """
        _validate_metadata(self.file_name, self.content_type)
        return self


class HomeworkFileInput(BaseModel):
    """Описание выбранного файла; готовность и storage_key не задаются клиентом."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=10485760)
    content_type: str = Field(min_length=1, max_length=127)
    content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """Проверяет заявленное описание до вызова другого сервиса.

        Returns:
            Проверенное описание.

        Raises:
            ValueError: Небезопасное имя либо несовместимый тип.
        """
        _validate_metadata(self.file_name, self.content_type)
        return self


def _validate_metadata(file_name: str, content_type: str) -> None:
    """Проверяет имя и allowlist, не утверждая безопасность ещё не полученных байтов.

    Args:
        file_name: Название для отображения.
        content_type: Заявленный MIME.

    Raises:
        ValueError: Недопустимые имя или формат.
    """
    if any(char in file_name for char in ("/", "\\")) or any(
        unicodedata.category(char) == "Cc" for char in file_name
    ):
        raise ValueError("Expected a safe file name")
    expected = CONTENT_TYPES.get(PurePosixPath(file_name).suffix.lower())
    if expected is None or content_type != expected:
        raise ValueError("File extension and declared content type must match")
