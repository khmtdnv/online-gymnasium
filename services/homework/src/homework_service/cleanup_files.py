"""Одноразовая безопасная уборка старых объектов; расписание запуска задаётся снаружи."""

import asyncio
import re
from collections.abc import Callable
from datetime import datetime, timedelta

from anyio import CancelScope, to_thread
from sqlalchemy.exc import SQLAlchemyError

from homework_service.application.ports.file_storage import FileStorage
from homework_service.application.ports.unit_of_work import UnitOfWork
from homework_service.config import HomeworkSettings
from homework_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from homework_service.infrastructure.minio_file_storage import create_file_storage
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


async def cleanup_files(
    storage: FileStorage,
    uow_factory: Callable[[], UnitOfWork],
    *,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Удаляет только неподтверждённые ключи попыток старше24часов.

    Args:
        storage: Собственный приватный bucket с постраничным listing.
        uow_factory: Новая авторитетная SQL-транзакция на каждый объект.
        clock: Только тестовая подмена часов; в production берётся время PostgreSQL.

    Returns:
        Количество подтверждённых удалений. Строки ДЗ/вложений не удаляются.

    Raises:
        OSError: Хранилище недоступно; дальнейшая уборка прекращается.
        SQLAlchemyError: Нельзя подтвердить ненужность объекта; удаление запрещено.

    Попытка может стать ready только в первый час по PostgreSQL. Объект старше
    суток уже не может впервые привязаться после этой проверки. Серверы БД и
    MinIO должны иметь синхронизированное время, как и остальные узлы сервиса.
    """
    deleted = 0
    objects = storage.list_objects("homework/")
    try:
        while item := await to_thread.run_sync(next, objects, None):
            key, modified = item
            match = re.fullmatch(
                r"homework/([1-9][0-9]*)/files/([1-9][0-9]*)/[0-9a-f]{32}", key
            )
            answer_match = re.fullmatch(
                r"homework/([1-9][0-9]*)/answers/([1-9][0-9]*)/files/([1-9][0-9]*)/[0-9a-f]{32}",
                key,
            )
            match = answer_match or match
            if match is None or any(
                int(value) > 2147483647 for value in match.groups()
            ):
                continue
            async with uow_factory() as uow:
                now = await uow.files.get_current_time() if clock is None else clock()
                if modified.tzinfo is None or modified.utcoffset() is None:
                    raise OSError("Storage returned an invalid object timestamp")
                if modified >= now - timedelta(hours=24):
                    continue
                repository = uow.answer_files if answer_match is not None else uow.files
                file = await repository.get_by_id(
                    int(match[3] if answer_match is not None else match[2])
                )
                if file is not None and file.storage_key == key:
                    continue
            # Никогда не держим SQL-транзакцию во время сетевого удаления.
            await to_thread.run_sync(storage.delete, key)
            deleted += 1
    finally:
        close = getattr(objects, "close", None)
        if close is not None:
            with CancelScope(shield=True):
                await to_thread.run_sync(close)
    return deleted


async def main() -> None:
    """Собирает отдельный operational-процесс из env и всегда закрывает ресурсы.

    Raises:
        OSError: Не настроены права хранилища или операция не завершилась.
        SQLAlchemyError: Своя БД недоступна.
    """
    settings = HomeworkSettings()
    storage = create_file_storage(settings)
    if storage is None:
        raise OSError("File storage is not configured")
    engine = None
    try:
        engine = create_engine(settings.database_url)
        sessions = create_session_factory(engine)
        deleted = await cleanup_files(storage, lambda: SqlAlchemyUnitOfWork(sessions))
        print(f"Removed unused homework file objects: {deleted}")
    finally:
        try:
            if engine is not None:
                await engine.dispose()
        finally:
            storage.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError, SQLAlchemyError, ValueError:
        raise SystemExit(
            "Homework file cleanup failed; retry after restoring dependencies"
        ) from None
