"""Тестовый магазин проверяется до POST; сумма и ключ не меняются при повторе."""

import asyncio
import base64
from uuid import UUID, uuid4

import httpx
import pytest


def test_real_adapter_uses_test_shop_and_stable_provider_key():
    from billing_service.contracts import PaymentSnapshot
    from billing_service.provider import ProviderUnavailableError, YooKassaClient

    snapshot = PaymentSnapshot(
        id=1, order_id=2, amount_kopecks=300000, provider_key=uuid4()
    )
    payment_id = str(uuid4())
    calls = []
    shop_test = True
    response_changes = {}

    def respond(request):
        calls.append(
            (request.method, request.url.path, request.headers, request.content)
        )
        assert request.url.host == "api.yookassa.ru"
        assert (
            request.headers["authorization"]
            == "Basic " + base64.b64encode(b"123:test-secret").decode()
        )
        if request.url.path == "/v3/me":
            return httpx.Response(
                200, json={"account_id": "123", "test": shop_test, "status": "enabled"}
            )
        return httpx.Response(
            200,
            json={
                "id": payment_id,
                "status": "pending",
                "paid": False,
                "test": True,
                "amount": {"value": "3000.00", "currency": "RUB"},
                "metadata": {"order_id": "2", "payment_id": "1"},
                "recipient": {"account_id": "123"},
                "confirmation": {
                    "type": "redirect",
                    "confirmation_url": "https://yoomoney.ru/checkout",
                },
                **response_changes,
            },
        )

    async def run():
        nonlocal shop_test, response_changes
        import json

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = YooKassaClient(
                http, "123", "test-secret", "http://localhost:8080/billing"
            )
            result = await client.create_payment(snapshot)
            assert result.id == UUID(payment_id)
            again = await client.create_payment(snapshot)
            assert again == result
            posts = [call for call in calls if call[0] == "POST"]
            assert len(posts) == 2 and posts[0][2]["Idempotence-Key"] == str(
                snapshot.provider_key
            )
            assert posts[0][3] == posts[1][3]
            assert json.loads(posts[0][3])["amount"] == {
                "value": "3000.00",
                "currency": "RUB",
            }
            shop_test = False
            with pytest.raises(ProviderUnavailableError):
                await client.create_payment(snapshot)
            assert len([call for call in calls if call[0] == "POST"]) == 2
            shop_test = True
            for change in (
                {"test": False},
                {"amount": {"value": "1.00", "currency": "RUB"}},
                {"recipient": {"account_id": "other"}},
                {"metadata": {"order_id": "999", "payment_id": "1"}},
                {
                    "confirmation": {
                        "type": "redirect",
                        "confirmation_url": "https://evil.test/checkout",
                    }
                },
            ):
                response_changes = change
                with pytest.raises(ProviderUnavailableError):
                    await client.create_payment(snapshot)

    asyncio.run(run())


def test_refund_retry_uses_the_same_key_even_if_first_call_already_refunded():
    from billing_service.contracts import PaymentSnapshot, RefundSnapshot
    from billing_service.provider import YooKassaClient

    payment_id, refund_id, key = uuid4(), uuid4(), uuid4()
    snapshot = RefundSnapshot(
        id=3,
        provider_key=key,
        payment=PaymentSnapshot(
            id=1,
            order_id=2,
            amount_kopecks=300000,
            provider_key=uuid4(),
            provider_id=payment_id,
        ),
    )
    posted = 0

    def respond(request):
        nonlocal posted
        if request.url.path == "/v3/me":
            return httpx.Response(
                200, json={"account_id": "123", "test": True, "status": "enabled"}
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": str(payment_id),
                    "status": "succeeded",
                    "paid": True,
                    "test": True,
                    "amount": {"value": "3000.00", "currency": "RUB"},
                    "metadata": {"order_id": "2", "payment_id": "1"},
                    "recipient": {"account_id": "123"},
                    "refundable": posted == 0,
                    "refunded_amount": {
                        "value": "3000.00" if posted else "0.00",
                        "currency": "RUB",
                    },
                },
            )
        assert request.headers["Idempotence-Key"] == str(key)
        posted += 1
        return httpx.Response(
            200,
            json={
                "id": str(refund_id),
                "status": "succeeded",
                "payment_id": str(payment_id),
                "amount": {"value": "3000.00", "currency": "RUB"},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = YooKassaClient(
                http, "123", "secret", "http://localhost:8080/billing"
            )
            first = await client.create_refund(snapshot)
            assert await client.create_refund(snapshot) == first
            assert posted == 2

    asyncio.run(run())
