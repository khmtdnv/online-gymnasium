"""Доступ к занятиям ограничивается только подтверждённой задолженностью."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from gateway_service.api.tuition_access import check_student_tuition
from gateway_service.domain.user import Role
from gateway_service.infrastructure.billing_client import BillingRequestError
from gateway_service.infrastructure.journal_client import JournalUnavailableError


class Enrolled:
    async def get_current_class_id(self, student_id):
        return 1


@pytest.mark.parametrize("allowed,expected", [(True, None), (False, 403)])
def test_student_access_follows_billing(allowed, expected):
    class Billing:
        async def quarter_access(self, student_id):
            return allowed

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(enforce_tuition_access=True),
            billing_client=Billing(),
            journal_client=Enrolled(),
        )
    )
    user = SimpleNamespace(id=uuid4(), role=Role.STUDENT)

    async def run():
        if expected:
            with pytest.raises(HTTPException) as exc:
                await check_student_tuition(app, user)
            assert exc.value.status_code == expected
        else:
            await check_student_tuition(app, user)

    asyncio.run(run())


def test_billing_failure_is_not_reported_as_unpaid():
    class Billing:
        async def quarter_access(self, student_id):
            raise BillingRequestError()

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(enforce_tuition_access=True),
            billing_client=Billing(),
            journal_client=Enrolled(),
        )
    )
    user = SimpleNamespace(id=uuid4(), role=Role.STUDENT)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_student_tuition(app, user))
    assert exc.value.status_code == 503


def test_journal_failure_does_not_turn_into_payment_required():
    class Journal:
        async def get_current_class_id(self, student_id):
            raise JournalUnavailableError

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(enforce_tuition_access=True),
            journal_client=Journal(),
        )
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            check_student_tuition(app, SimpleNamespace(id=uuid4(), role=Role.STUDENT))
        )
    assert exc.value.status_code == 503


def test_teacher_is_not_blocked_by_student_tuition():
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(enforce_tuition_access=True), billing_client=None
        )
    )
    asyncio.run(
        check_student_tuition(app, SimpleNamespace(id=uuid4(), role=Role.TEACHER))
    )


def test_unpaid_student_cannot_open_learning_routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from gateway_service.api.router import router
    from gateway_service.api.security import get_authenticated_user

    class Billing:
        async def quarter_access(self, student_id):
            return False

    app = FastAPI()
    app.state.settings = SimpleNamespace(enforce_tuition_access=True)
    app.state.billing_client = Billing()
    app.state.journal_client = Enrolled()
    app.dependency_overrides[get_authenticated_user] = lambda: SimpleNamespace(
        id=uuid4(), role=Role.STUDENT
    )
    app.include_router(router)
    with TestClient(app) as client:
        for path in (
            "/api/v1/homework",
            "/api/v1/my-homework",
            "/api/v1/my-schedule?week_start=2026-11-16",
        ):
            assert client.get(path).status_code == 403


def test_unpaid_student_cannot_use_pen_socket():
    from gateway_service.api.pen import check_pen_access

    class Billing:
        async def quarter_access(self, student_id):
            return False

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(enforce_tuition_access=True),
            billing_client=Billing(),
            journal_client=Enrolled(),
        )
    )
    user = SimpleNamespace(id=uuid4(), role=Role.STUDENT)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_pen_access(app, user, 1, user.id))
    assert exc.value.status_code == 403


def test_student_without_class_is_not_marked_as_owing_tuition():
    class NoClass:
        async def get_current_class_id(self, student_id):
            return None

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(enforce_tuition_access=True),
            billing_client=None,
            journal_client=NoClass(),
        )
    )
    asyncio.run(
        check_student_tuition(app, SimpleNamespace(id=uuid4(), role=Role.STUDENT))
    )
