"""Подготовка схем аналитики без изменения старой истории."""

from pathlib import Path

from analytics_service.config import AnalyticsApiSettings
from analytics_service.infrastructure.clickhouse_connection import create_client
from analytics_service.infrastructure.teacher_id_migration import prepare_uuid_schema


def prepare_audit_schema(client) -> None:
    """Создаёт только новую таблицу аудита, повторный запуск безопасен."""
    path = Path(__file__).resolve().parents[3] / "sql/004_audit_events.sql"
    client.command(path.read_text(encoding="utf-8"))


def main() -> None:
    """Создаёт схемы нагрузки и аудита, сохраняя старые таблицы."""
    settings = AnalyticsApiSettings()
    client = create_client(settings)
    try:
        prepare_uuid_schema(client)
        prepare_audit_schema(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
