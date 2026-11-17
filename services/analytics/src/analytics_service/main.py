"""Точка сборки зависимостей и запуска HTTP-приложения сервиса."""

from analytics_service.api.app import create_app
from analytics_service.config import AnalyticsApiSettings
from analytics_service.infrastructure.clickhouse_audit_repository import (
    ClickHouseAuditRepository,
)
from analytics_service.infrastructure.clickhouse_connection import create_client
from analytics_service.infrastructure.clickhouse_workload_repository import (
    ClickHouseWorkloadRepository,
)

settings = AnalyticsApiSettings()
client = create_client(settings)
app = create_app(
    repository_factory=lambda: ClickHouseWorkloadRepository(client),
    audit_repository_factory=lambda: ClickHouseAuditRepository(client),
    audit_service_token=settings.gateway_read_service_token,
)
