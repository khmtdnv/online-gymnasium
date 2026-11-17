"""Финансовые данные доступны только владельцу, связанному родителю и admin."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
from fastapi import FastAPI


def test_quarter_payment_requires_current_enrollment():
    from gateway_service.api.billing import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role

    student_id = UUID(int=2)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_user] = lambda: GetCurrentUserResult(
        id=student_id, email="student@example.test", role=Role.STUDENT
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=student_id, role=Role.STUDENT, is_active=True
                    )
                )
            )
        )

    app.state.uow_factory = uow
    app.state.journal_client = SimpleNamespace(
        get_current_class_id=AsyncMock(return_value=None)
    )
    app.state.billing_client = SimpleNamespace(start=AsyncMock())

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/billing/payments",
                json={
                    "student_id": str(student_id),
                    "study_month": "2026-11-01",
                    "period_type": "quarter",
                    "request_key": str(UUID(int=5)),
                },
            )
            assert response.status_code == 409
            app.state.billing_client.start.assert_not_awaited()

    asyncio.run(run())


def test_billing_checks_parent_link_before_refresh_and_admin_before_refund():
    from gateway_service.api.billing import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role

    role = Role.PARENT
    linked = False
    student_id = UUID(int=2)
    viewer_id = UUID(int=1)
    payment = {
        "id": 7,
        "order_id": 3,
        "student_id": str(student_id),
        "payer_id": str(viewer_id),
        "study_month": "2026-10-01",
        "amount_kopecks": 300000,
        "currency": "RUB",
        "status": "pending",
        "confirmation_url": "https://yoomoney.ru/checkout/payments/test",
        "provider_id": str(UUID(int=3)),
        "created_at": datetime.now(UTC).isoformat(),
        "refund_status": None,
    }
    app = FastAPI()
    app.include_router(router)

    async def viewer():
        return GetCurrentUserResult(
            id=viewer_id, email="parent@example.test", role=role
        )

    app.dependency_overrides[get_authenticated_user] = viewer

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(
            users=SimpleNamespace(
                has_parent_student_link=AsyncMock(side_effect=lambda *args: linked),
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=student_id,
                        role=Role.STUDENT,
                        is_active=True,
                    )
                ),
            )
        )

    app.state.uow_factory = uow
    app.state.billing_client = SimpleNamespace(
        get_payment=AsyncMock(return_value=payment),
        refresh=AsyncMock(return_value=payment),
        refund=AsyncMock(return_value=payment),
    )

    async def run():
        nonlocal linked, role
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = "/api/v1/billing/payments/7"
            assert (await client.post(path + "/refresh")).status_code == 403
            app.state.billing_client.refresh.assert_not_awaited()
            linked = True
            response = await client.post(path + "/refresh")
            assert response.status_code == 200
            assert response.json()["id"] == 7
            assert response.headers["cache-control"] == "private, no-store"
            assert (
                await client.post(
                    path + "/refund", json={"request_key": str(UUID(int=4))}
                )
            ).status_code == 403
            app.state.billing_client.refund.assert_not_awaited()
            role = Role.TEACHER
            assert (await client.post(path + "/refresh")).status_code == 403
            role = Role.STUDENT
            assert (
                await client.post(
                    "/api/v1/billing/payments",
                    json={
                        "student_id": str(student_id),
                        "study_month": "2026-10-01",
                        "request_key": str(UUID(int=5)),
                        "amount_kopecks": 1,
                    },
                )
            ).status_code == 422
            role = Role.ADMIN
            assert (
                await client.post(
                    path + "/refund", json={"request_key": str(UUID(int=4))}
                )
            ).status_code == 202

    asyncio.run(run())


def test_admin_history_includes_names_from_one_batch_lookup():
    """История показывает ФИО, а недоступного ученика обозначает явно."""
    from gateway_service.api.billing import router
    from gateway_service.api.security import get_authenticated_user
    from gateway_service.application.auth import GetCurrentUserResult
    from gateway_service.domain.user import Role

    student_id = UUID(int=2)
    missing_id = UUID(int=3)
    payment = {
        "id": 7,
        "order_id": 3,
        "student_id": student_id,
        "payer_id": UUID(int=1),
        "study_month": "2026-10-01",
        "amount_kopecks": 300000,
        "currency": "RUB",
        "status": "pending",
        "confirmation_url": None,
        "provider_id": None,
        "created_at": datetime.now(UTC),
        "refund_status": None,
    }
    users = AsyncMock(
        return_value=[
            SimpleNamespace(
                id=student_id,
                last_name="Хаматдинов",
                first_name="Рустам",
                middle_name="Табрисович",
            )
        ]
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(users=SimpleNamespace(get_by_ids=users))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_user] = lambda: GetCurrentUserResult(
        id=UUID(int=1),
        email="admin@example.test",
        role=Role.ADMIN,
    )
    app.state.uow_factory = uow
    app.state.billing_client = SimpleNamespace(
        payments=AsyncMock(
            return_value=[
                payment,
                {**payment, "id": 8},
                {**payment, "id": 9, "student_id": missing_id},
            ]
        )
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/billing/payments")
        assert response.status_code == 200
        assert [row["student_name"] for row in response.json()] == [
            "Хаматдинов Рустам Табрисович",
            "Хаматдинов Рустам Табрисович",
            "Пользователь недоступен",
        ]
        users.assert_awaited_once()
        assert set(users.call_args.args[0]) == {student_id, missing_id}

    asyncio.run(run())
