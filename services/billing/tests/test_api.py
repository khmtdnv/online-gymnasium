"""Private API и реальная PG: webhook — повод GET, а не доказательство оплаты."""

import asyncio
import json
import os
from datetime import date
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_private_api_and_webhook_recheck_authoritative_provider():
    from billing_service.app import create_app
    from billing_service.contracts import ProviderPayment, StartPayment
    from billing_service.models import Base
    from billing_service.provider import YooKassaClient
    from billing_service.service import BillingService
    from billing_service.storage import BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BILLING_TEST_DATABASE_URL missing")
    assert make_url(url).database.startswith("billing_test_")

    async def run():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        store = BillingStore(async_sessionmaker(engine, expire_on_commit=False))
        calls = []
        response = {}
        refund_keys = []
        refund_id = uuid4()

        def external(request):
            calls.append((request.method, request.url.path))
            if request.url.path == "/v3/me":
                return httpx.Response(
                    200, json={"account_id": "123", "test": True, "status": "enabled"}
                )
            if request.method == "POST" and request.url.path == "/v3/refunds":
                refund_keys.append(request.headers["Idempotence-Key"])
                response["refundable"] = False
                response["refunded_amount"] = {"value": "3000.00", "currency": "RUB"}
                if len(refund_keys) == 1:
                    raise httpx.ReadTimeout("Refund ACK lost", request=request)
                return httpx.Response(
                    200,
                    json={
                        "id": str(refund_id),
                        "payment_id": response["id"],
                        "status": "succeeded",
                        "amount": {"value": "3000.00", "currency": "RUB"},
                    },
                )
            assert request.method == "GET"
            return httpx.Response(200, json=response)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(external)
        ) as provider_http:
            service = BillingService(
                store,
                YooKassaClient(
                    provider_http, "123", "secret", "http://localhost:8080/billing"
                ),
                300000,
            )
            app = create_app(service, "gateway-billing-only")
            headers = {"Authorization": "Bearer gateway-billing-only"}
            async with httpx.AsyncClient(
                base_url="http://test", transport=httpx.ASGITransport(app=app)
            ) as client:
                assert (await client.get("/internal/config")).status_code == 401
                config = await client.get("/internal/config", headers=headers)
                assert config.json() == {
                    "configured": True,
                    "test_only": True,
                    "price_kopecks": 300000,
                    "quarter_price_kopecks": 900000,
                    "currency": "RUB",
                }
                forged = {
                    "student_id": str(uuid4()),
                    "payer_id": str(uuid4()),
                    "study_month": "2026-10-01",
                    "request_key": str(uuid4()),
                    "amount_kopecks": 1,
                }
                assert (
                    await client.post(
                        "/internal/payments", json=forged, headers=headers
                    )
                ).status_code == 422
                notice = {"event": "payment.succeeded", "object_id": str(uuid4())}
                assert (
                    await client.post("/internal/webhook", json=notice, headers=headers)
                ).status_code == 200
                assert calls == []
                command = StartPayment(
                    student_id=uuid4(),
                    payer_id=uuid4(),
                    study_month=date(2026, 10, 1),
                    request_key=uuid4(),
                )
                payment = await store.reserve_payment(command, 300000)
                provider_id = uuid4()
                response = {
                    "id": str(provider_id),
                    "status": "pending",
                    "paid": False,
                    "test": True,
                    "amount": {"value": "3000.00", "currency": "RUB"},
                    "metadata": {
                        "order_id": str(payment.order_id),
                        "payment_id": str(payment.id),
                    },
                    "recipient": {"account_id": "123"},
                    "confirmation": {
                        "type": "redirect",
                        "confirmation_url": "https://yoomoney.ru/pay",
                    },
                }
                await store.apply_payment(
                    payment.id,
                    ProviderPayment.model_validate_json(json.dumps(response)),
                )
                response = response | {"status": "succeeded", "paid": True}
                notice["object_id"] = str(provider_id)
                for event in (
                    "payment.succeeded",
                    "payment.succeeded",
                    "payment.canceled",
                ):
                    assert (
                        await client.post(
                            "/internal/webhook",
                            json=notice | {"event": event},
                            headers=headers,
                        )
                    ).status_code == 200
                assert (await store.view_payment(payment.id)).status == "succeeded"
                assert calls == [("GET", f"/v3/payments/{provider_id}")] * 3
                response = response | {"amount": {"value": "1.00", "currency": "RUB"}}
                assert (
                    await client.post("/internal/webhook", json=notice, headers=headers)
                ).status_code == 503
                assert (await store.view_payment(payment.id)).status == "succeeded"
                response["amount"] = {"value": "3000.00", "currency": "RUB"}
                response["refundable"] = True
                refund_command = {"actor_id": str(uuid4()), "request_key": str(uuid4())}
                refund_path = f"/internal/payments/{payment.id}/refund"
                assert (
                    await client.post(refund_path, json=refund_command, headers=headers)
                ).status_code == 503
                retried = await client.post(
                    refund_path, json=refund_command, headers=headers
                )
                assert retried.status_code == 202
                assert retried.json()["status"] == "refunded"
                assert len(refund_keys) == 2 and refund_keys[0] == refund_keys[1]
        await engine.dispose()

    asyncio.run(run())
