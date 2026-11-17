"""Отчёт и аудит одного экрана могут одновременно обращаться к ClickHouse."""

import asyncio
import os
from datetime import date

from analytics_service.application.audit import AuditQuery, ProgressQuery
from analytics_service.config import AnalyticsApiSettings
from analytics_service.infrastructure.clickhouse_audit_repository import (
    ClickHouseAuditRepository,
)
from analytics_service.workers.migrate_audit import prepare_audit_schema


def test_concurrent_reads_do_not_share_server_session(legacy_clickhouse):
    from analytics_service.infrastructure.clickhouse_connection import create_client

    prepare_audit_schema(legacy_clickhouse)
    client = create_client(
        AnalyticsApiSettings(
            clickhouse_host="127.0.0.1",
            clickhouse_port=int(os.environ["ANALYTICS_TEST_CLICKHOUSE_PORT"]),
            clickhouse_database=legacy_clickhouse.database,
            clickhouse_user="default",
            clickhouse_password="",
            _env_file=None,
        )
    )
    repository = ClickHouseAuditRepository(client)

    async def run():
        query = AuditQuery(date_from=date(2026, 10, 1), date_to=date(2026, 10, 22))
        await asyncio.gather(
            asyncio.to_thread(client.command, "SELECT sleep(0.2)"),
            repository.list_events(query),
            repository.get_progress(
                ProgressQuery(
                    class_id=7, date_from=query.date_from, date_to=query.date_to
                )
            ),
        )

    try:
        asyncio.run(run())
    finally:
        client.close()
