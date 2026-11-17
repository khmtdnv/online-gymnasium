"""Проверка/сохранение байтов и короткая условная фиксация вне сетевой транзакции."""

import logging
from collections.abc import Callable
from datetime import datetime
from secrets import token_hex
from typing import BinaryIO

from anyio import CapacityLimiter, to_thread

from homework_service.application.homework_files import (
    HomeworkFileInput,
    HomeworkFileResult,
)
from homework_service.application.ports.errors import HomeworkNotFoundError
from homework_service.application.ports.file_storage import FileStorage
from homework_service.application.ports.unit_of_work import UnitOfWork
from homework_service.domain.homework_file import HomeworkFile
from homework_service.infrastructure.file_validation import validate_file

logger = logging.getLogger(__name__)


async def save_file(
    file: HomeworkFile,
    stream: BinaryIO,
    uow_factory: Callable[[], UnitOfWork],
    storage: FileStorage,
    *,
    limiter: CapacityLimiter | None = None,
) -> tuple[str, datetime]:
    """Проверяет содержимое и сохраняет его по новому серверному ключу.

    Args:
        file: Ожидаемое вложение из PostgreSQL после проверки прав.
        stream: Seekable-поток; закрывается владельцем HTTP-запроса.
        uow_factory: Короткая транзакция только для чтения серверного времени.
        storage: Приватное хранилище приложения.
        limiter: Общий предел потоковых операций процесса.

    Returns:
        Отдельный ключ попытки и время её начала из PostgreSQL.

    Raises:
        ValueError: Некорректные байты либо вложение ещё не сохранено.
        OSError: Хранилище или серверное время недоступны.
    """
    if file.id is None:
        raise ValueError("Cannot upload an unreserved file")
    expected = HomeworkFileInput(
        file_name=file.file_name,
        size_bytes=file.size_bytes,
        content_type=file.content_type,
        content_sha256=file.content_sha256,
    )
    async with uow_factory() as uow:
        started_at = await uow.files.get_current_time()
    key = f"homework/{file.homework_id}/files/{file.id}/{token_hex(16)}"

    def write() -> None:
        content_type = validate_file(stream, expected)
        storage.put(key, stream, file.size_bytes, content_type)

    await to_thread.run_sync(write, limiter=limiter)
    return key, started_at


async def finish_upload(
    file: HomeworkFile,
    storage_key: str,
    started_at: datetime,
    uow_factory: Callable[[], UnitOfWork],
    storage: FileStorage,
) -> HomeworkFileResult:
    """Публикует один ключ и подтверждает результат после неизвестного commit.

    Args:
        file: Ожидаемое вложение, прочитанное до передачи байтов.
        storage_key: Новый ключ текущей попытки.
        started_at: Начало попытки по PostgreSQL, не время браузера.
        uow_factory: Новая транзакция фиксации, затем отдельная для восстановления.
        storage: Удаление только доказанно проигравшего объекта вне транзакции.

    Returns:
        Метаданные ready, включая результат победившего параллельного запроса.

    Raises:
        HomeworkNotFoundError: Вложение удалено либо связано с другим заданием.
        OSError: Попытка истекла или результат не удалось подтвердить.
    """
    try:
        async with uow_factory() as uow:
            saved = await uow.files.mark_ready(file.id, storage_key, started_at)
            if saved is None:
                saved = await uow.files.get_by_id(file.id)
            if saved is None or saved.homework_id != file.homework_id:
                raise HomeworkNotFoundError
            if saved.upload_status != "ready":
                raise OSError("File upload attempt expired")
    except Exception:
        # Ошибка commit не доказывает rollback. Сначала авторитетная новая сессия;
        # при её сбое объект остаётся для безопасной отложенной уборки.
        async with uow_factory() as uow:
            saved = await uow.files.get_by_id(file.id)
        if (
            saved is None
            or saved.homework_id != file.homework_id
            or saved.upload_status != "ready"
        ):
            raise

    if saved.storage_key != storage_key:
        try:
            await to_thread.run_sync(storage.delete, storage_key)
        except OSError:
            logger.warning("Unused homework file cleanup deferred")
    return HomeworkFileResult.from_file(saved)
