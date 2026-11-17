"""Journal отличает отсутствие периода от недоступного/некорректного ответа."""

import asyncio
from uuid import UUID

import httpx
import pytest


def test_journal_client_checks_subject_and_batch_contract():
    from gateway_service.infrastructure.journal_client import (
        JournalClient,
        JournalUnavailableError,
    )

    async def run():
        mode = "missing"

        def respond(request):
            assert request.headers["Authorization"] == "Bearer read-only"
            if request.url.path.endswith("/lookup"):
                return httpx.Response(
                    200,
                    json=[]
                    if mode == "bad"
                    else [
                        {
                            "id": 7,
                            "name": "7А",
                            "study_year": 2026,
                            "created_at": "2026-10-21T00:00:00Z",
                        }
                    ],
                )
            if mode == "missing":
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "student_id": str(UUID(int=2)),
                    "class_id": 7,
                    "joined_at": "2026-10-21T00:00:00Z",
                    "left_at": None,
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://journal"
        ) as http:
            client = JournalClient(http, "read-only")
            assert await client.get_current_class_id(UUID(int=1)) is None
            assert await client.get_class_names([7]) == {7: "7А"}
            mode = "bad"
            with pytest.raises(JournalUnavailableError):
                await client.get_current_class_id(UUID(int=1))
            with pytest.raises(JournalUnavailableError):
                await client.get_class_names([7])

    asyncio.run(run())
