"""Новые четвертные счета не изменяют смысл прежних месячных платежей."""

import asyncio
import os
from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from billing_service.contracts import StartPayment


def test_quarter_invoice_can_be_issued_before_payment_and_is_idempotent():
    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from billing_service.models import Base, PaymentRow, TuitionOrderRow
    from billing_service.storage import BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BILLING_TEST_DATABASE_URL missing")
    assert make_url(url).database.startswith("billing_test_")

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            store = BillingStore(sessions)
            student_id = uuid4()
            await asyncio.gather(
                *(
                    store.ensure_quarter_order(student_id, date(2027, 1, 1), 900000)
                    for _ in range(2)
                )
            )
            await store.ensure_quarter_order(student_id, date(2027, 1, 1), 1200000)
            async with sessions() as session:
                row = (
                    await session.scalars(
                        select(TuitionOrderRow).where(
                            TuitionOrderRow.student_id == student_id
                        )
                    )
                ).one()
                assert (row.period_type, row.status, row.amount_kopecks) == (
                    "quarter",
                    "unpaid",
                    900000,
                )
                assert (
                    await session.scalar(
                        select(func.count(PaymentRow.id)).where(
                            PaymentRow.order_id == row.id
                        )
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_quarter_order_does_not_collide_with_monthly_order():
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from billing_service.models import Base
    from billing_service.storage import BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BILLING_TEST_DATABASE_URL missing")
    assert make_url(url).database.startswith("billing_test_")

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            store = BillingStore(async_sessionmaker(engine, expire_on_commit=False))
            data = {
                "student_id": uuid4(),
                "payer_id": uuid4(),
                "study_month": date(2026, 9, 1),
            }
            monthly = await store.reserve_payment(
                StartPayment(**data, request_key=uuid4()), 300000
            )
            await store.ensure_quarter_order(
                data["student_id"], data["study_month"], 900000
            )
            quarterly = await store.reserve_payment(
                StartPayment(**data, request_key=uuid4(), period_type="quarter"), 900000
            )
            assert monthly.order_id != quarterly.order_id
            assert (await store.view_payment(monthly.id)).period_type == "month"
            assert (await store.view_payment(quarterly.id)).period_type == "quarter"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_refunded_quarter_can_be_paid_again():
    from sqlalchemy import update
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from billing_service.models import Base, PaymentRow, TuitionOrderRow
    from billing_service.storage import BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BILLING_TEST_DATABASE_URL missing")
    assert make_url(url).database.startswith("billing_test_")

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            store = BillingStore(sessions)
            command = StartPayment(
                student_id=uuid4(),
                payer_id=uuid4(),
                study_month=date(2026, 9, 1),
                period_type="quarter",
                request_key=uuid4(),
            )
            await store.ensure_quarter_order(
                command.student_id, command.study_month, 900000
            )
            first = await store.reserve_payment(command, 900000)
            async with sessions() as session, session.begin():
                await session.execute(
                    update(PaymentRow)
                    .where(PaymentRow.id == first.id)
                    .values(status="refunded")
                )
                await session.execute(
                    update(TuitionOrderRow)
                    .where(TuitionOrderRow.id == first.order_id)
                    .values(status="refunded")
                )
            second = await store.reserve_payment(
                command.model_copy(update={"request_key": uuid4()}), 900000
            )
            assert second.id != first.id
            assert second.order_id == first.order_id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cannot_pay_quarter_without_preexisting_invoice():
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from billing_service.models import Base
    from billing_service.storage import BillingConflictError, BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Isolated PostgreSQL required")
    assert make_url(url).database.startswith("billing_test_")

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            store = BillingStore(async_sessionmaker(engine, expire_on_commit=False))
            command = StartPayment(
                student_id=uuid4(),
                payer_id=uuid4(),
                study_month=date(2026, 9, 1),
                period_type="quarter",
                request_key=uuid4(),
            )
            with pytest.raises(BillingConflictError):
                await store.reserve_payment(command, 900000)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_quarter_payment_accepts_only_start_of_school_quarter():
    data = {
        "student_id": uuid4(),
        "payer_id": uuid4(),
        "request_key": uuid4(),
        "period_type": "quarter",
    }
    assert StartPayment(**data, study_month=date(2026, 9, 1)).period_type == "quarter"
    with pytest.raises(ValidationError):
        StartPayment(**data, study_month=date(2026, 10, 1))


def test_legacy_monthly_payment_stays_monthly():
    value = StartPayment(
        student_id=uuid4(),
        payer_id=uuid4(),
        request_key=uuid4(),
        study_month=date(2026, 10, 1),
    )
    assert value.period_type == "month"


def test_unknown_quarter_does_not_treat_monthly_payment_as_quarter_paid():
    from billing_service.service import BillingService

    class Store:
        async def quarter_status(self, student_id, start):
            assert start == date(2026, 9, 1)

    async def run():
        service = BillingService(Store(), None, 300000)
        assert await service.quarter_access(uuid4(), date(2026, 10, 1)) is False
        assert await service.quarter_access(uuid4(), date(2026, 7, 1)) is True

    asyncio.run(run())


def test_private_quarter_access_endpoint_requires_service_authentication():
    import httpx

    from billing_service.app import create_app

    class Service:
        async def quarter_access(self, student_id, today):
            return False

    async def run():
        app = create_app(Service(), "service-secret")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/internal/students/{uuid4()}/quarter-access"
            assert (await client.get(path)).status_code == 401
            response = await client.get(
                path, headers={"Authorization": "Bearer service-secret"}
            )
            assert response.status_code == 200
            assert response.json() == {"allowed": False}

    asyncio.run(run())
