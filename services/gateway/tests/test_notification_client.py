"""Чужой адресат и внешний URL не должны попасть в личный список портала."""

import asyncio
from uuid import uuid4

import httpx
import pytest

from gateway_service.infrastructure.notification_client import (
    NotificationClient,
    NotificationRequestError,
)


def test_notification_client_rejects_foreign_recipient_and_unsafe_link():
    user = uuid4()
    row = {
        "id": 1,
        "event_id": str(uuid4()),
        "recipient_id": str(user),
        "title": "Документ готов",
        "body": "Откройте документ.",
        "link": "/billing",
        "created_at": "2026-10-22T12:00:00Z",
        "read_at": None,
    }

    def respond(request):
        assert request.headers["Authorization"] == "Bearer notices-only"
        assert request.url.params["user_id"] == str(user)
        return httpx.Response(200, json=[row])

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://notifications"
        ) as http:
            client = NotificationClient(http, "notices-only")
            assert (await client.list_for(user, 0))[0].id == 1
            row["recipient_id"] = str(uuid4())
            with pytest.raises(NotificationRequestError):
                await client.list_for(user, 0)
            row["recipient_id"] = str(user)
            row["link"] = "https://evil.test"
            with pytest.raises(NotificationRequestError):
                await client.list_for(user, 0)

    asyncio.run(run())
