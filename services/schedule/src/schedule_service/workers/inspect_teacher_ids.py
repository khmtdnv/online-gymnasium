"""Печатает безопасный read-only отчёт об ID перед переходом Schedule на UUID."""

import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from schedule_service.config import Settings
from schedule_service.infrastructure.teacher_id_migration import (
    TeacherIdMigrationError,
    inspect_teacher_ids,
)


async def run(database_url: str) -> dict[str, object]:
    """Собирает отчёт в read-only транзакции и всегда освобождает соединения.

    Args:
        database_url: Адрес PostgreSQL из настроек, не попадающий в отчёт.

    Returns:
        JSON-совместимые ID, счётчики и тип колонки без credentials.

    Raises:
        TeacherIdMigrationError: Старые данные не соответствуют ожидаемой схеме.
        SQLAlchemyError: Не удалось подключиться или прочитать данные.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            inventory = await connection.run_sync(inspect_teacher_ids)
        return {
            "column_type": inventory.column_type,
            "lesson_count": inventory.lesson_count,
            "snapshot_count": inventory.snapshot_count,
            "lesson_teacher_ids": sorted(inventory.lesson_teacher_ids),
            "snapshot_teacher_ids": sorted(inventory.snapshot_teacher_ids),
            "legacy_ids": sorted(inventory.legacy_ids),
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Запускает отчёт отдельно от API, не раскрывая адрес БД при ошибке."""
    try:
        result = asyncio.run(run(Settings().database_url))
    except TeacherIdMigrationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
    except (SQLAlchemyError, OSError, ValueError):  # fmt: skip
        print("Cannot inspect Schedule teacher IDs", file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
