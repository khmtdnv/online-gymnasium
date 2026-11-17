"""Изолированные ClickHouse-ресурсы для миграции и сквозной проверки."""

import os
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def legacy_clickhouse():
    """Создаёт собственную тестовую БД и удаляет только её после сценария."""
    port = os.environ.get("ANALYTICS_TEST_CLICKHOUSE_PORT")
    if not port:
        pytest.skip("Нужен отдельный тестовый ClickHouse")
    import clickhouse_connect

    database = "analytics_test_teacher_uuid_" + uuid4().hex
    admin = clickhouse_connect.get_client(host="127.0.0.1", port=int(port))
    admin.command(f"CREATE DATABASE {database}")
    client = clickhouse_connect.get_client(
        host="127.0.0.1", port=int(port), database=database
    )
    try:
        for sql in (
            (Path(__file__).parents[1] / "sql" / "001_schema.sql")
            .read_text()
            .split(";")
        ):
            if sql.strip():
                client.command(sql)
        yield client
    finally:
        client.close()
        admin.command(f"DROP DATABASE {database} SYNC")
        admin.close()
