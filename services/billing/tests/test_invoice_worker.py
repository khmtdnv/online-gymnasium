"""Выставление счетов использует только подтверждённый состав Journal."""

import asyncio
import os
from datetime import date
from uuid import UUID

import httpx
import pytest

from billing_service.invoice_worker import issue_quarter_invoices


def test_worker_persists_unpaid_invoices_and_repeats_without_duplicates():
    from sqlalchemy import func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from billing_service.models import Base, TuitionOrderRow
    from billing_service.storage import BillingStore

    url = os.getenv("BILLING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Isolated PostgreSQL required")
    assert make_url(url).database.startswith("billing_test_")
    student = UUID("00000000-0000-4000-8000-000000000002")

    def journal(request):
        if request.url.path == "/internal/classes":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "name": "7А",
                        "study_year": 2026,
                        "created_at": "2026-09-01T00:00:00Z",
                    }
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "student_id": str(student),
                    "class_id": 7,
                    "joined_at": "2026-09-01T00:00:00Z",
                    "left_at": None,
                }
            ],
        )

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(journal), base_url="http://journal"
            ) as http:
                for _ in range(2):
                    await issue_quarter_invoices(
                        http, "test", BillingStore(sessions), date(2026, 10, 1), 900000
                    )
            async with sessions() as session:
                rows = (
                    await session.scalars(
                        select(TuitionOrderRow)
                        .where(TuitionOrderRow.student_id == student)
                        .order_by(TuitionOrderRow.study_month)
                    )
                ).all()
                assert [(row.study_month, row.status) for row in rows] == [
                    (date(2026, 9, 1), "unpaid"),
                    (date(2026, 11, 1), "unpaid"),
                ]
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(TuitionOrderRow)
                        .where(TuitionOrderRow.student_id == student)
                    )
                    == 2
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_issue_current_and_next_quarters_only_for_current_students():
    student = UUID("00000000-0000-4000-8000-000000000001")
    orders = set()

    def journal(request):
        assert request.headers["Authorization"] == "Bearer billing-secret"
        if request.url.path == "/internal/classes":
            assert request.url.params["study_year"] == "2026"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "name": "7А",
                        "study_year": 2026,
                        "created_at": "2026-09-01T00:00:00Z",
                    }
                ],
            )
        assert request.url.path == "/internal/classes/7/current-periods"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "student_id": str(student),
                    "class_id": 7,
                    "joined_at": "2026-09-01T00:00:00Z",
                    "left_at": None,
                }
            ],
        )

    class Store:
        async def ensure_quarter_order(self, student_id, start, price):
            orders.add((student_id, start, price))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(journal), base_url="http://journal"
        ) as http:
            await issue_quarter_invoices(
                http, "billing-secret", Store(), date(2026, 10, 1), 900000
            )
            await issue_quarter_invoices(
                http, "billing-secret", Store(), date(2026, 10, 1), 900000
            )

    asyncio.run(run())
    assert orders == {
        (student, date(2026, 9, 1), 900000),
        (student, date(2026, 11, 1), 900000),
    }


def test_rejects_foreign_or_closed_periods_before_issuing_orders():
    def journal(request):
        if request.url.path == "/internal/classes":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 7,
                        "name": "7А",
                        "study_year": 2026,
                        "created_at": "2026-09-01T00:00:00Z",
                    }
                ],
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "student_id": "00000000-0000-4000-8000-000000000001",
                    "class_id": 8,
                    "joined_at": "2026-09-01T00:00:00Z",
                    "left_at": None,
                }
            ],
        )

    class Store:
        async def ensure_quarter_order(self, *args):
            pytest.fail("No invoice may be issued for a foreign period")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(journal), base_url="http://journal"
        ) as http:
            with pytest.raises(ValueError):
                await issue_quarter_invoices(
                    http, "billing-secret", Store(), date(2026, 10, 1), 900000
                )

    asyncio.run(run())
