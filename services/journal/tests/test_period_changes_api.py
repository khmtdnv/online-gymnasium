"""Проверяет реальные маршруты, права и обработчики изменения периодов."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest

from journal_service.api.dependencies import ServicePrincipal, get_authenticated_service
from journal_service.app import create_app
from journal_service.application.ports.errors import UserLookupUnavailableError
from journal_service.application.ports.gateway_user_reader import GatewayUserInfo
from journal_service.config import JournalSettings
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod

STUDENT = UUID("aaaaaaaa-0000-4000-8000-000000000001")
BASE = f"/internal/students/{STUDENT}/current-class-period"
HEADERS = {"Authorization": "Bearer test-token", "X-Actor-ID": "42"}
JOINED = datetime(2026, 9, 1, tzinfo=UTC)
BOUNDARY = datetime(2026, 10, 16, tzinfo=UTC)


@pytest.fixture
def setup():
    """Настоящее приложение с внешними reader/UoW на границах."""
    settings = JournalSettings(
        database_url="postgresql+asyncpg://unused/test",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.classes.get_class_by_id = AsyncMock(return_value=Class("7Б", 2026, id=2))
    uow.class_periods.get_period_for_update = AsyncMock(
        return_value=(StudentClassPeriod(STUDENT, 1, id=10, joined_at=JOINED))
    )
    uow.class_periods.get_current_period_for_student = AsyncMock(return_value=None)
    uow.class_periods.close_period = AsyncMock(
        return_value=(
            StudentClassPeriod(STUDENT, 1, id=10, joined_at=JOINED, left_at=BOUNDARY)
        )
    )
    uow.class_periods.create_period = AsyncMock(
        return_value=(StudentClassPeriod(STUDENT, 2, id=11, joined_at=BOUNDARY))
    )
    uow.outbox.add_event = AsyncMock()
    factory = Mock(return_value=uow)
    reader = SimpleNamespace(
        get_user=AsyncMock(
            return_value=(GatewayUserInfo(id=STUDENT, role="student", is_active=True))
        )
    )
    app = create_app(settings, factory, gateway_user_reader=reader)
    return SimpleNamespace(
        app=app, settings=settings, factory=factory, reader=reader, uow=uow
    )


def send(app, action="transfer", headers=None, body=None, expected="10"):
    """Передаёт HTTP через ASGI без внешнего сервера."""

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            if action == "transfer":
                return await client.post(
                    BASE + "/transfer",
                    headers=(HEADERS if headers is None else headers),
                    json={"target_class_id": 2, "expected_period_id": 10}
                    if body is None
                    else body,
                )
            return await client.delete(
                BASE,
                headers=HEADERS if headers is None else headers,
                params={} if expected is None else {"expected_period_id": expected},
            )

    return asyncio.run(request())


def test_transfer_returns_period_and_trusted_actor(setup):
    """Не теряет новый период, server request_id и staff actor в событии."""
    response = send(setup.app, headers={**HEADERS, "X-Request-ID": "untrusted"})
    assert response.status_code == 200
    assert response.json() == {
        "id": 11,
        "student_id": str(STUDENT),
        "class_id": 2,
        "joined_at": "2026-10-16T00:00:00Z",
        "left_at": None,
    }
    event = setup.uow.outbox.add_event.await_args.args[0]
    assert event.actor_id == "42"
    assert event.request_id == response.headers["x-request-id"] != "untrusted"
    assert BASE + "/transfer" not in setup.app.openapi()["paths"]


def test_end_is_bodyless_and_independent_of_gateway(setup):
    """Завершение работает даже без настроенного reader и не отдаёт JSON в204."""
    app = create_app(setup.settings, setup.factory)
    response = send(app, "end")
    assert response.status_code == 204
    assert response.content == b""
    setup.reader.get_user.assert_not_awaited()
    assert setup.uow.outbox.add_event.await_args.args[0].period_id == 10


@pytest.mark.parametrize("action", ["transfer", "end"])
@pytest.mark.parametrize(
    "case,status",
    [
        ("stale", 409),
        ("missing_actor", 422),
        ("bad_actor", 422),
        ("unauthenticated", 401),
        ("permission", 403),
    ],
)
def test_mutation_rejects_invalid_context(setup, action, case, status):
    """ID сотрудника не заменяет токен, право и проверку expected."""
    headers = dict(HEADERS)
    if case == "stale":
        setup.uow.class_periods.get_period_for_update.return_value = StudentClassPeriod(
            STUDENT, 1, id=10, joined_at=JOINED, left_at=BOUNDARY
        )
        setup.uow.class_periods.get_current_period_for_student.return_value = (
            StudentClassPeriod(STUDENT, 2, id=11, joined_at=BOUNDARY)
        )
    elif case == "missing_actor":
        headers.pop("X-Actor-ID")
    elif case == "bad_actor":
        headers["X-Actor-ID"] = "9223372036854775808"
    elif case == "unauthenticated":
        headers.pop("Authorization")
    else:
        setup.app.dependency_overrides[get_authenticated_service] = lambda: (
            ServicePrincipal(
                service_name="backoffice", permissions=frozenset({"classes:read"})
            )
        )
    response = send(setup.app, action, headers=headers)
    assert response.status_code == status
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    setup.uow.class_periods.close_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"target_class_id": 2, "expected_period_id": True},
        {"target_class_id": "2", "expected_period_id": 10},
        {"target_class_id": 0, "expected_period_id": 10},
        {"target_class_id": 2, "expected_period_id": 10, "actor_id": "99"},
    ],
)
def test_transfer_strict_body_is_checked_before_gateway(setup, body):
    """Лишние поля и неверные числовые типы не запускают действие."""
    assert send(setup.app, body=body).status_code == 422
    setup.factory.assert_not_called()
    setup.reader.get_user.assert_not_awaited()


@pytest.mark.parametrize("expected", [None, "0", "-1", "2147483648", "abc"])
def test_end_requires_bounded_expected_id(setup, expected):
    """Нельзя завершать период без указания исходной версии формы."""
    assert send(setup.app, "end", expected=expected).status_code == 422
    setup.factory.assert_not_called()


@pytest.mark.parametrize(
    "case,status",
    [
        ("missing_user", 404),
        ("invalid_user", 422),
        ("lookup_unavailable", 503),
        ("missing_class", 404),
    ],
)
def test_transfer_business_errors_are_safe(setup, case, status):
    """Ошибки владельца данных не становятся успешным переводом."""
    if case == "missing_user":
        setup.reader.get_user.return_value = None
    elif case == "invalid_user":
        setup.reader.get_user.return_value = GatewayUserInfo(
            id=STUDENT, role="teacher", is_active=True
        )
    elif case == "lookup_unavailable":
        setup.reader.get_user.side_effect = UserLookupUnavailableError(
            "secret test-token"
        )
    else:
        setup.uow.classes.get_class_by_id.return_value = None
    response = send(setup.app)
    assert response.status_code == status
    assert "test-token" not in response.text
    setup.uow.class_periods.close_period.assert_not_awaited()
