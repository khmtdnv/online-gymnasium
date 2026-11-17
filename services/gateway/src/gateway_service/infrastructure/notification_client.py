"""Служебный клиент личного списка с проверкой адресата каждой записи."""

from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.notifications import Notification, NotificationCount


class NotificationRequestError(Exception):
    """Владелец не подтвердил запрос или вернул чужие/повреждённые данные."""

    def __init__(self, status=503):
        self.status = status


class NotificationClient:
    """Не передаёт JWT в сервис и не доверяет UUID адресата из браузерного ввода."""

    def __init__(self, http: httpx.AsyncClient, token: str):
        self.http, self.headers = http, {"Authorization": f"Bearer {token}"}

    async def _request(self, method, path, *, params=None, body=None):
        try:
            response = await self.http.request(
                method,
                "/internal/notifications" + path,
                params=params,
                json=body,
                headers=self.headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                raise NotificationRequestError(404)
            if len(response.content) > 1048576:
                raise NotificationRequestError
            return response
        except httpx.HTTPError as exc:
            raise NotificationRequestError from exc

    async def list_for(self, user_id: UUID, offset: int) -> list[Notification]:
        """Чужой адресат в любом элементе отклоняет всю страницу."""
        response = await self._request(
            "GET", "", params={"user_id": str(user_id), "offset": offset}
        )
        try:
            if response.status_code != 200:
                raise NotificationRequestError
            rows = TypeAdapter(list[Notification]).validate_json(response.content)
            if (
                len(rows) > 50
                or len({row.id for row in rows}) != len(rows)
                or any(row.recipient_id != user_id for row in rows)
            ):
                raise NotificationRequestError
            return rows
        except ValidationError as exc:
            raise NotificationRequestError from exc

    async def count(self, user_id: UUID) -> int:
        """Счётчик относится к текущему пользователю Gateway."""
        response = await self._request(
            "GET", "/count", params={"user_id": str(user_id)}
        )
        try:
            if response.status_code != 200:
                raise NotificationRequestError
            return NotificationCount.model_validate_json(response.content).unread
        except ValidationError as exc:
            raise NotificationRequestError from exc

    async def mark_read(self, id_: int, user_id: UUID) -> None:
        """204 подтверждает только собственную запись; повтор безопасен."""
        response = await self._request(
            "POST", f"/{id_}/read", body={"user_id": str(user_id)}
        )
        if response.status_code != 204 or response.content:
            raise NotificationRequestError
