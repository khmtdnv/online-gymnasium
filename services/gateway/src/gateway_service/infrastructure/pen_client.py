"""Служебное чтение и запись штрихов, без пересылки пользовательского JWT."""

from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.pen import PenBatch, SavedPenBatch


class PenUnavailableError(Exception):
    """Сохранение или история не подтверждены владельцем Pen."""


class PenRequestError(Exception):
    """Pen подтвердил конфликт последовательности или заполнение страницы."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class PenClient:
    """Использует пул Gateway и отдельную пару служебных credentials."""

    def __init__(self, client: httpx.AsyncClient, service_token: str) -> None:
        self._client = client
        self._headers = {"Authorization": f"Bearer {service_token}"}

    async def _request(self, method, lesson_id, student_id, **kwargs):
        try:
            response = await self._client.request(
                method,
                f"/internal/lessons/{lesson_id}/students/{student_id}/batches",
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise PenUnavailableError from exc
        if response.status_code in {409, 413}:
            raise PenRequestError(response.status_code)
        if response.status_code != 200 or len(response.content) > 1048576:
            raise PenUnavailableError
        return response

    async def history(
        self, lesson_id: int, student_id: UUID, *, after: int
    ) -> list[SavedPenBatch]:
        """Требует последовательную страницу, не пропуская потерянные пачки."""
        response = await self._request(
            "GET", lesson_id, student_id, params={"after": after}
        )
        try:
            rows = TypeAdapter(list[SavedPenBatch]).validate_json(response.content)
        except ValidationError as exc:
            raise PenUnavailableError from exc
        if (
            len(rows) > 100
            or [row.sequence for row in rows]
            != list(range(after + 1, after + 1 + len(rows)))
            or len({row.batch_id for row in rows}) != len(rows)
        ):
            raise PenUnavailableError
        return rows

    async def append(
        self, lesson_id: int, student_id: UUID, batch: PenBatch
    ) -> SavedPenBatch:
        """Проверяет, что ACK относится ровно к отправленной пачке."""
        response = await self._request(
            "POST", lesson_id, student_id, json=batch.model_dump(mode="json")
        )
        try:
            row = SavedPenBatch.model_validate_json(response.content)
        except ValidationError as exc:
            raise PenUnavailableError from exc
        if row.model_dump(exclude={"id"}) != batch.model_dump():
            raise PenUnavailableError
        return row
