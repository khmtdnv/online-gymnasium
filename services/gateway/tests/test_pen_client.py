"""Повреждённая история не превращается в подтверждённые штрихи."""

import asyncio
from uuid import uuid4

import httpx
import pytest


def test_pen_client_rejects_malformed_and_unordered_history():
    from gateway_service.infrastructure.pen_client import PenClient, PenUnavailableError

    response = []

    def handle(request):
        assert request.headers["Authorization"] == "Bearer pen-only"
        assert "access_token" not in str(request.url)
        return httpx.Response(200, json=response)

    async def run():
        nonlocal response
        async with httpx.AsyncClient(
            base_url="http://pen", transport=httpx.MockTransport(handle)
        ) as http:
            client = PenClient(http, "pen-only")
            assert await client.history(1, uuid4(), after=0) == []
            response = [
                {
                    "id": 1,
                    "batch_id": str(uuid4()),
                    "sequence": 2,
                    "stroke_id": str(uuid4()),
                    "points": [{"x": 0.1, "y": 0.1}],
                    "finished": True,
                }
            ]
            with pytest.raises(PenUnavailableError):
                await client.history(1, uuid4(), after=0)

    asyncio.run(run())
