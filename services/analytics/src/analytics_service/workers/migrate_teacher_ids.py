"""Отдельная команда проверки/переноса ClickHouse-истории, не startup hook."""

import argparse
import json
from pathlib import Path

import clickhouse_connect
from clickhouse_connect.driver.exceptions import ClickHouseError

from analytics_service.config import AnalyticsApiSettings
from analytics_service.infrastructure.teacher_id_migration import (
    TeacherIdMigrationError,
    legacy_teacher_ids,
    load_teacher_id_mapping,
    migrate_teacher_ids,
)


def main() -> None:
    """Читает env-настройки, выполняет явную команду и всегда закрывает клиент."""
    parser = argparse.ArgumentParser(description="Offline UUID history migration")
    parser.add_argument("--mapping-file", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    client = None
    try:
        mapping = (
            load_teacher_id_mapping(args.mapping_file) if args.mapping_file else {}
        )
        settings = AnalyticsApiSettings()
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )
        ids = sorted(legacy_teacher_ids(client))
        count = migrate_teacher_ids(client, mapping, check_only=args.check)
        print(
            json.dumps(
                {"legacy_teacher_ids": ids, "check_only": args.check, "count": count}
            )
        )
    except TeacherIdMigrationError as exc:
        parser.exit(2, f"{exc}\n")
    except (ClickHouseError,OSError,ValueError):  # fmt: skip
        parser.exit(2, "Cannot migrate Analytics teacher IDs\n")
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
