"""Локальные метаданные файлов ученических ответов."""

from datetime import datetime
from typing import Protocol

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.domain.homework_answer_file import HomeworkAnswerFile


class HomeworkAnswerFileRepository(Protocol):
    """Не смешивает ответ ученика с общим файлом задания."""

    async def add_files(
        self, answer_id: int, files: list[HomeworkFileInput]
    ) -> list[HomeworkAnswerFile]:
        """Резервирует ожидаемые файлы общей транзакцией со сдачей."""
        ...

    async def get_by_id(self, file_id: int) -> HomeworkAnswerFile | None:
        """Читает файл и его родительский homework_id через свой локальный join."""
        ...

    async def list_for_answers(
        self, answer_ids: list[int]
    ) -> dict[int, list[HomeworkAnswerFile]]:
        """Получает вложения страницы одним запросом."""
        ...

    async def has_pending(self, answer_id: int) -> bool:
        """Проверяет, остались ли незагруженные файлы перед оцениванием."""
        ...

    async def mark_ready(
        self, file_id: int, storage_key: str, started_at: datetime
    ) -> HomeworkAnswerFile | None:
        """Фиксирует свежую попытку; родитель блокируется вызывающим сценарием."""
        ...
