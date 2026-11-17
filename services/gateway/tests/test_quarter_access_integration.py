"""Gateway и настоящий Billing с отдельной PostgreSQL; провайдер подменён."""

import asyncio
import importlib.util
import os
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway_service.api.tuition_access import check_student_tuition
from gateway_service.domain.user import Role
from gateway_service.infrastructure.billing_client import BillingClient


def test_payment_and_refund_immediately_change_student_access():
    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url or importlib.util.find_spec("billing_service") is None:
        pytest.skip("Isolated Billing database and source are required")
    assert make_url(url).database.startswith("billing_test_")
    from billing_service.app import create_app
    from billing_service.contracts import ProviderPayment, StartPayment
    from billing_service.models import Base
    from billing_service.service import BillingService
    from billing_service.storage import BillingStore
    from billing_service.study_quarters import study_quarter_for_date

    quarter = study_quarter_for_date(datetime.now(ZoneInfo("Europe/Moscow")).date())
    if quarter is None:
        pytest.skip("Demo school is on summer break")

    class Journal:
        async def get_current_class_id(self, student_id):
            return 1

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            store = BillingStore(async_sessionmaker(engine, expire_on_commit=False))
            billing = create_app(BillingService(store, None, 300000), "test-token")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=billing), base_url="http://billing"
            ) as http:
                user = SimpleNamespace(id=uuid4(), role=Role.STUDENT)
                app = SimpleNamespace(
                    state=SimpleNamespace(
                        settings=SimpleNamespace(enforce_tuition_access=True),
                        journal_client=Journal(),
                        billing_client=BillingClient(http, "test-token"),
                    )
                )
                with pytest.raises(HTTPException) as exc:
                    await check_student_tuition(app, user)
                assert exc.value.status_code == 403
                await store.ensure_quarter_order(user.id, quarter.start, 900000)
                payment = await store.reserve_payment(
                    StartPayment(
                        student_id=user.id,
                        payer_id=user.id,
                        study_month=quarter.start,
                        period_type="quarter",
                        request_key=uuid4(),
                    ),
                    900000,
                )
                provider = ProviderPayment.model_validate(
                    {
                        "id": str(uuid4()),
                        "status": "succeeded",
                        "paid": True,
                        "test": True,
                        "amount": {"value": "9000.00", "currency": "RUB"},
                        "recipient": {"account_id": "test"},
                        "metadata": {},
                    }
                )
                await store.apply_payment(payment.id, provider)
                await check_student_tuition(app, user)
                await store.apply_payment(
                    payment.id,
                    provider.model_copy(update={"refunded_amount": provider.amount}),
                )
                with pytest.raises(HTTPException) as exc:
                    await check_student_tuition(app, user)
                assert exc.value.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())
