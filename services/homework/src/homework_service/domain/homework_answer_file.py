"""Приватное вложение конкретной попытки, не общий файл задания."""

from dataclasses import dataclass
from typing import Literal

from homework_service.domain.homework_file import HomeworkFile


@dataclass(slots=True)
class HomeworkAnswerFile:
    """Повторяет правила формата, но хранит отдельную связь с ответом ученика."""

    answer_id: int
    homework_id: int
    file_name: str
    size_bytes: int
    content_type: str
    content_sha256: str
    id: int | None = None
    upload_status: Literal["pending", "ready"] = "pending"
    storage_key: str | None = None

    def __post_init__(self) -> None:
        """Проверяет ссылки, метаданные и соответствие ready приватному ключу.

        Raises:
            ValueError: Недопустимые локальные поля.
        """
        for value in (
            self.answer_id,
            self.homework_id,
            *(() if self.id is None else (self.id,)),
        ):
            if type(value) is not int or not 1 <= value <= 2147483647:
                raise ValueError("Invalid answer file ID")
        HomeworkFile.validate_metadata(
            self.file_name, self.size_bytes, self.content_type, self.content_sha256
        )
        if self.upload_status == "pending" and self.storage_key is None:
            return
        if (
            self.upload_status == "ready"
            and isinstance(self.storage_key, str)
            and self.storage_key
        ):
            return
        raise ValueError("Invalid answer file state")
