"""Недостоверные ответы Billing не превращаются в доверенный финансовый DTO."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from gateway_service.infrastructure.billing_client import (
    BillingClient,
    BillingRequestError,
)


def test_billing_response_owner_and_redirect_are_checked_without_post_retry():
    body = {
        "id": 1,
        "order_id": 2,
        "student_id": str(UUID(int=3)),
        "payer_id": str(UUID(int=4)),
        "study_month": "2026-10-01",
        "amount_kopecks": 300000,
        "currency": "RUB",
        "status": "pending",
        "confirmation_url": "https://yoomoney.ru/test",
        "provider_id": None,
        "created_at": datetime.now(UTC).isoformat(),
        "refund_status": None,
    }
    calls = []
    timeout = False

    def respond(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer private-billing"
        if timeout:
            raise httpx.ReadTimeout("unknown result", request=request)
        return httpx.Response(202, json=body)

    async def run():
        nonlocal timeout
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://billing"
        ) as http:
            client = BillingClient(http, "private-billing")
            command = {
                "student_id": str(UUID(int=3)),
                "payer_id": str(UUID(int=4)),
                "study_month": "2026-10-01",
                "request_key": str(UUID(int=5)),
            }
            assert (await client.start(command)).id == 1
            body["confirmation_url"] = "https://yoomoney.ru.evil.test/pay"
            with pytest.raises(BillingRequestError):
                await client.start(command)
            body["confirmation_url"] = None
            body["student_id"] = str(UUID(int=6))
            with pytest.raises(BillingRequestError):
                await client.start(command)
            timeout = True
            before = len(calls)
            with pytest.raises(BillingRequestError):
                await client.start(command)
            assert len(calls) == before + 1

    asyncio.run(run())
