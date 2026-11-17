"""Сумму квитанции определяет подтверждённый платёж, а не форма администратора."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI


def test_document_receipt_uses_verified_billing_snapshot_and_admin_identity():
    from gateway_service.api.documents import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role

    role = Role.PARENT
    actor = uuid4()
    job_id = uuid4()
    student_id = uuid4()
    payment = {
        "id": 7,
        "order_id": 3,
        "student_id": str(student_id),
        "payer_id": str(uuid4()),
        "study_month": "2026-10-01",
        "amount_kopecks": 300000,
        "currency": "RUB",
        "status": "pending",
        "confirmation_url": None,
        "provider_id": None,
        "created_at": "2026-10-22T12:00:00Z",
        "refund_status": None,
    }
    app = FastAPI()
    app.include_router(router)

    async def viewer():
        return GetCurrentUserResult(id=actor, email="admin@example.test", role=role)

    app.dependency_overrides[get_authenticated_user] = viewer
    app.state.billing_client = SimpleNamespace(
        get_payment=AsyncMock(side_effect=lambda id_: payment)
    )
    recorded = []

    async def create(creator, body):
        recorded.append((creator, body))
        return {"id": str(job_id), "document_type": "receipt", "status": "pending"}

    app.state.documents_client = SimpleNamespace(create=create)

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=student_id,
                        first_name="Иван",
                        last_name="Петров",
                        middle_name="Сергеевич",
                    )
                )
            )
        )

    app.state.uow_factory = uow

    async def run():
        nonlocal role
        body = {
            "document_type": "receipt",
            "request_key": str(uuid4()),
            "payload": {"payment_id": 7},
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (
                await client.post("/api/v1/documents", json=body)
            ).status_code == 403
            assert recorded == []
            role = Role.ADMIN
            assert (
                await client.post(
                    "/api/v1/documents",
                    json=body | {"payload": {"payment_id": 7, "amount_kopecks": 1}},
                )
            ).status_code == 422
            assert (
                await client.post("/api/v1/documents", json=body)
            ).status_code == 409
            payment["status"] = "succeeded"
            result = await client.post("/api/v1/documents", json=body)
            assert result.status_code == 202
            assert UUID(result.json()["id"]) == job_id
            assert recorded[0][0] == actor
            assert recorded[0][1]["payload"] == {
                "payment_id": 7,
                "student_full_name": "Петров Иван Сергеевич",
                "study_month": "2026-10-01",
                "period_type": "month",
                "amount_kopecks": 300000,
                "currency": "RUB",
            }

    asyncio.run(run())
