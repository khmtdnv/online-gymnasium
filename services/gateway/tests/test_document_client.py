"""Авторизованный PDF-клиент не выдаёт чужой ответ и закрывает большой поток."""

import asyncio
from uuid import uuid4

import httpx
import pytest

from gateway_service.infrastructure.document_client import (
    DocumentClient,
    DocumentRequestError,
)


def test_document_client_checks_job_identity_and_closes_oversized_pdf():
    actor, job_id = uuid4(), uuid4()
    closed = False

    class LargePdf(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"%PDF" + b"x" * (5 * 1024 * 1024)

        async def aclose(self):
            nonlocal closed
            closed = True

    def respond(request):
        assert request.headers["Authorization"] == "Bearer document-only"
        assert request.headers["X-Actor-ID"] == str(actor)
        if request.url.path.endswith("/content"):
            return httpx.Response(
                200, headers={"Content-Type": "application/pdf"}, stream=LargePdf()
            )
        return httpx.Response(
            200,
            json={
                "id": str(uuid4()),
                "document_type": "contract",
                "status": "completed",
                "created_at": "2026-10-22T12:00:00Z",
            },
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://documents"
        ) as http:
            client = DocumentClient(http, "document-only")
            with pytest.raises(DocumentRequestError):
                await client.get_job(actor, job_id)
            with pytest.raises(DocumentRequestError):
                await client.content(actor, job_id)
            assert closed

    asyncio.run(run())
