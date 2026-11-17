"""Служебные JSON/PDF запросы с UUID создателя из Gateway, не браузера."""

from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.documents import CreatedDocument, DocumentJob


class DocumentRequestError(Exception):
    """Известный отказ владельца документа или нарушение его контракта."""

    def __init__(self, status=503):
        self.status = status


class DocumentClient:
    """Ограничивает ответы и не использует произвольные download_url из JSON."""

    def __init__(self, http: httpx.AsyncClient, token: str):
        self.http, self.token = http, token

    def _headers(self, creator: UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Actor-ID": str(creator)}

    async def _json(self, method, path, creator, contract, *, body=None, params=None):
        try:
            response = await self.http.request(
                method,
                "/internal/documents" + path,
                json=body,
                params=params,
                headers=self._headers(creator),
                timeout=10.0,
                follow_redirects=False,
            )
            if response.status_code in (404, 409):
                raise DocumentRequestError(response.status_code)
            if (
                response.status_code not in (200, 202)
                or len(response.content) > 1048576
            ):
                raise DocumentRequestError
            return TypeAdapter(contract).validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise DocumentRequestError from exc

    async def create(self, creator: UUID, body: dict) -> CreatedDocument:
        """Сохраняет ключ повторного POST; не повторяет неизвестный запрос автоматически."""
        row = await self._json("POST", "", creator, CreatedDocument, body=body)
        if row.document_type != body["document_type"]:
            raise DocumentRequestError
        return row

    async def list_jobs(self, creator: UUID, offset: int) -> list[DocumentJob]:
        """Читает только ограниченную страницу заданий данного создателя."""
        rows = await self._json(
            "GET", "", creator, list[DocumentJob], params={"offset": offset}
        )
        if len(rows) > 50 or len({row.id for row in rows}) != len(rows):
            raise DocumentRequestError
        return rows

    async def get_job(self, creator: UUID, job_id: UUID) -> DocumentJob:
        """Проверяет, что ответ относится к запрошенному UUID."""
        row = await self._json("GET", f"/{job_id}", creator, DocumentJob)
        if row.id != job_id:
            raise DocumentRequestError
        return row

    async def content(self, creator: UUID, job_id: UUID) -> bytes:
        """Закрывает HTTP-поток при ошибке и ограничивает PDF пятью МиБ."""
        try:
            async with self.http.stream(
                "GET",
                f"/internal/documents/{job_id}/content",
                headers=self._headers(creator),
                timeout=30.0,
                follow_redirects=False,
            ) as response:
                if response.status_code in (404, 409):
                    raise DocumentRequestError(response.status_code)
                if (
                    response.status_code != 200
                    or response.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                    != "application/pdf"
                ):
                    raise DocumentRequestError
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > 5 * 1024 * 1024:
                        raise DocumentRequestError
                    data.extend(chunk)
                if not data.startswith(b"%PDF"):
                    raise DocumentRequestError
                return bytes(data)
        except httpx.HTTPError as exc:
            raise DocumentRequestError from exc
