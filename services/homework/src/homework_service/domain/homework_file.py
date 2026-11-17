"""Ожидаемый файл задания и его локальные правила, без доступа к MinIO."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

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


@dataclass(slots=True)
class HomeworkFile:
    """Одно ожидаемое вложение; готовое содержит приватный ключ объекта."""

    homework_id: int
    file_name: str
    size_bytes: int
    content_type: str
    content_sha256: str
    id: int | None = None
    upload_status: Literal["pending", "ready"] = "pending"
    storage_key: str | None = None

    def __post_init__(self) -> None:
        """Проверяет метаданные и согласованность состояния с ключом.

        Raises:
            ValueError: Недопустимые поля или готовность без сохранённого объекта.
        """
        ids = [self.homework_id]
        if self.id is not None:
            ids.append(self.id)
        for value in ids:
            if type(value) is not int or not 1 <= value <= 2147483647:
                raise ValueError("File IDs must be positive PostgreSQL INTEGERs")
        self.validate_metadata(
            self.file_name, self.size_bytes, self.content_type, self.content_sha256
        )
        if self.upload_status not in ("pending", "ready"):
            raise ValueError("Unknown file upload status")
        if self.upload_status == "pending" and self.storage_key is not None:
            raise ValueError("Pending files cannot have a storage key")
        if self.upload_status == "ready" and (
            not isinstance(self.storage_key, str) or not self.storage_key
        ):
            raise ValueError("Ready files require a storage key")

    @staticmethod
    def validate_metadata(
        file_name: str, size_bytes: int, content_type: str, content_sha256: str
    ) -> None:
        """Проверяет описание, не утверждая безопасность ещё не полученных байтов.

        Args:
            file_name: Название для отображения, не путь хранилища.
            size_bytes: Ожидаемый размер до 10 МиБ включительно.
            content_type: Заявленный MIME из разрешённого формата.
            content_sha256: Отпечаток выбранных байтов в нижнем hex-регистре.

        Raises:
            ValueError: Описание не соответствует локальному контракту.
        """
        if (
            not isinstance(file_name, str)
            or not 1 <= len(file_name) <= 255
            or any(char in file_name for char in ("/", "\\"))
            or any(unicodedata.category(char) == "Cc" for char in file_name)
        ):
            raise ValueError("Expected a safe file name of 1 to 255 characters")
        if type(size_bytes) is not int or not 1 <= size_bytes <= 10485760:
            raise ValueError("File size must be between 1 byte and 10 MiB")
        expected_type = CONTENT_TYPES.get(PurePosixPath(file_name).suffix.lower())
        if expected_type is None or content_type != expected_type:
            raise ValueError("File extension and declared content type must match")
        if (
            not isinstance(content_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None
        ):
            raise ValueError("Expected a SHA-256 hex digest")
