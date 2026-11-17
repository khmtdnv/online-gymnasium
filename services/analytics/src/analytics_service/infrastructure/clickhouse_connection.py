"""Сборка HTTP-клиента ClickHouse для независимых запросов одного процесса."""

import clickhouse_connect

from analytics_service.config import AnalyticsApiSettings


def create_client(settings: AnalyticsApiSettings):
    """Не делит серверную сессию между параллельными read-запросами API."""
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        database=settings.clickhouse_database,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        connect_timeout=5,
        send_receive_timeout=15,
        autogenerate_session_id=False,
    )
