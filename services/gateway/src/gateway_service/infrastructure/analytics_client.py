"""Ограниченный read-клиент Analytics с собственным служебным секретом."""

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.analytics import (
    AuditEvent,
    AuditQuery,
    ProgressQuery,
    ProgressRow,
)


class AnalyticsUnavailableError(Exception):
    """Analytics не подтвердил данные или нарушил ожидаемый контракт."""


class AnalyticsQueryTooLargeError(Exception):
    """Владелец попросил сузить слишком большой отчёт."""


class AnalyticsClient:
    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        self._client = http_client
        self._headers = {"Authorization": f"Bearer {service_token}"}

    async def _read(self, path: str, query, item_type, maximum: int):
        """Не повторяет запрос автоматически и не пересылает JWT пользователя."""
        try:
            params = query.model_dump(mode="json", exclude_none=True)
            response = await self._client.get(
                path,
                params=params,
                headers=self._headers,
                timeout=10.0,
                follow_redirects=False,
            )
            if response.status_code == 422:
                raise AnalyticsQueryTooLargeError
            if response.status_code != 200:
                raise AnalyticsUnavailableError
            rows = TypeAdapter(list[item_type]).validate_json(response.content)
            if len(rows) > maximum:
                raise AnalyticsUnavailableError
            return rows
        except (httpx.HTTPError, ValidationError) as exc:
            raise AnalyticsUnavailableError from exc

    async def get_progress(self, query: ProgressQuery) -> list[ProgressRow]:
        """Читает полный ограниченный отчёт класса без молчаливого усечения."""
        rows = await self._read("/internal/progress", query, ProgressRow, 1000)
        if len({(row.student_id, row.subject_id) for row in rows}) != len(rows):
            raise AnalyticsUnavailableError
        return rows

    async def list_events(self, query: AuditQuery) -> list[AuditEvent]:
        """Читает страницу журнала; повтор event_id в ней — нарушение контракта."""
        rows = await self._read("/internal/audit", query, AuditEvent, query.limit)
        if len({row.event_id for row in rows}) != len(rows):
            raise AnalyticsUnavailableError
        return rows
