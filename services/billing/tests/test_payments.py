"""Изолированная реальная PG: идемпотентность, конкуренция, атомарный outbox."""

import asyncio
import json
import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_real_payment_state_is_atomic_idempotent_and_never_reposts_after_key_expiry():
    from billing_service.contracts import (
        ProviderPayment,
        ProviderRefund,
        StartPayment,
        StartRefund,
    )
    from billing_service.models import Base, BillingEventRow, PaymentRow
    from billing_service.provider import YooKassaClient
    from billing_service.service import BillingService
    from billing_service.storage import BillingConflictError, BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BILLING_TEST_DATABASE_URL missing")
    assert make_url(url).database.startswith("billing_test_")

    async def run():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        store = BillingStore(sessions)
        command = StartPayment(
            student_id=uuid4(),
            payer_id=uuid4(),
            study_month=date(2026, 10, 1),
            request_key=uuid4(),
        )
        try:
            first, second = await asyncio.gather(
                store.reserve_payment(command, 300000),
                store.reserve_payment(command, 300000),
            )
            assert first.id == second.id and first.provider_key == second.provider_key
            with pytest.raises(BillingConflictError):
                await store.reserve_payment(
                    command.model_copy(update={"student_id": uuid4()}), 300000
                )
            with pytest.raises(BillingConflictError):
                await store.reserve_payment(
                    command.model_copy(update={"request_key": uuid4()}), 300000
                )
            provider_id = uuid4()
            payload = {
                "id": str(provider_id),
                "status": "succeeded",
                "paid": True,
                "test": True,
                "amount": {"value": "3000.00", "currency": "RUB"},
                "metadata": {
                    "order_id": str(first.order_id),
                    "payment_id": str(first.id),
                },
                "recipient": {"account_id": "123"},
            }
            value = ProviderPayment.model_validate_json(json.dumps(payload))

            def fail_event(*args):
                raise RuntimeError("outbox insert failed")

            event.listen(BillingEventRow, "before_insert", fail_event)
            try:
                with pytest.raises(RuntimeError):
                    await store.apply_payment(first.id, value)
            finally:
                event.remove(BillingEventRow, "before_insert", fail_event)
            assert (await store.get_payment(first.id)).status == "creating"
            await store.apply_payment(first.id, value)
            await store.apply_payment(first.id, value)
            old = ProviderPayment.model_validate_json(
                json.dumps(
                    payload
                    | {
                        "status": "pending",
                        "paid": False,
                        "confirmation": {
                            "type": "redirect",
                            "confirmation_url": "https://yoomoney.ru/pay",
                        },
                    }
                )
            )
            await store.apply_payment(first.id, old)
            assert (await store.get_payment(first.id)).status == "succeeded"
            selects = []

            def count_selects(connection, cursor, statement, parameters, context, many):
                if statement.lstrip().upper().startswith("SELECT"):
                    selects.append(1)

            event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
            try:
                assert (await store.list_orders(command.student_id, 50, 0))[
                    0
                ].status == "paid"
                assert len(selects) == 1
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_selects)
            async with sessions() as session:
                events = list(
                    await session.scalars(
                        select(BillingEventRow).where(
                            BillingEventRow.envelope["payload"][
                                "payment_id"
                            ].as_integer()
                            == first.id
                        )
                    )
                )
                assert len(events) == 1
                assert events[0].envelope["event_type"] == "billing.payment.succeeded"

            refund_command = StartRefund(actor_id=uuid4(), request_key=uuid4())
            refund = await store.reserve_refund(first.id, refund_command)
            assert (
                await store.reserve_refund(first.id, refund_command)
            ).id == refund.id
            with pytest.raises(BillingConflictError):
                await store.reserve_refund(
                    first.id, refund_command.model_copy(update={"request_key": uuid4()})
                )
            confirmed_refund = ProviderRefund(
                id=uuid4(),
                status="succeeded",
                payment_id=provider_id,
                amount={"value": "3000.00", "currency": "RUB"},
            )
            await store.apply_refund(refund.id, confirmed_refund)
            await store.apply_refund(refund.id, confirmed_refund)
            await store.apply_payment(first.id, value)
            result = await store.view_payment(first.id)
            assert result.status == "refunded" and result.refund_status == "succeeded"
            assert (await store.list_orders(command.student_id, 50, 0))[
                0
            ].status == "refunded"
            async with sessions() as session:
                events = list(
                    await session.scalars(
                        select(BillingEventRow).where(
                            BillingEventRow.envelope["payload"][
                                "payment_id"
                            ].as_integer()
                            == first.id
                        )
                    )
                )
                assert {row.envelope["event_type"] for row in events} == {
                    "billing.payment.succeeded",
                    "billing.payment.refunded",
                }
                assert len(events) == 2

            expired = await store.reserve_payment(
                command.model_copy(
                    update={"student_id": uuid4(), "request_key": uuid4()}
                ),
                300000,
            )
            async with sessions() as session, session.begin():
                await session.execute(
                    update(PaymentRow)
                    .where(PaymentRow.id == expired.id)
                    .values(created_at=datetime.now(UTC) - timedelta(hours=24))
                )

            def provider_request(request):
                assert request.method == "GET" and request.url.path == "/v3/me"
                return httpx.Response(
                    200, json={"account_id": "123", "test": True, "status": "enabled"}
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(provider_request)
            ) as http:
                service = BillingService(
                    store,
                    YooKassaClient(
                        http, "123", "secret", "http://localhost:8080/billing"
                    ),
                    300000,
                )
                result = await service.refresh_payment(expired.id)
                assert result.status == "manual_review"
                assert (
                    await store.get_payment(expired.id)
                ).provider_key == expired.provider_key
        finally:
            await engine.dispose()

    asyncio.run(run())
