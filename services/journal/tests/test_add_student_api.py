"""Проверяет закрытый PUT через настоящие зависимости и обработчик."""

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
PATH = f"/internal/students/{STUDENT}/current-class-period"
HEADERS = {"Authorization": "Bearer test-token", "X-Actor-ID": "42"}


@pytest.fixture
def setup():
    """Подменяет только Gateway и транзакционное хранилище."""
    settings = JournalSettings(
        database_url="postgresql+asyncpg://unused/test",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.classes.get_class_by_id = AsyncMock(return_value=Class("8А", 2026, id=10))
    uow.class_periods.get_current_period_for_student = AsyncMock(return_value=None)
    uow.class_periods.create_period = AsyncMock(
        return_value=StudentClassPeriod(
            STUDENT, 10, id=123, joined_at=datetime(2026, 10, 15, tzinfo=UTC)
        )
    )
    uow.outbox.add_event = AsyncMock()
    factory = Mock(return_value=uow)
    reader = SimpleNamespace(
        get_user=AsyncMock(
            return_value=GatewayUserInfo(id=STUDENT, role="student", is_active=True)
        )
    )
    app = create_app(settings, factory, gateway_user_reader=reader)
    return SimpleNamespace(
        app=app, settings=settings, factory=factory, reader=reader, uow=uow
    )


def put(app, *, body=None, headers=None, path=PATH):
    """Выполняет запрос без сетевого сервера; исключения проверяются как HTTP 500."""

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            return await client.put(
                path,
                json={"class_id": 10} if body is None else body,
                headers=HEADERS if headers is None else headers,
            )

    return asyncio.run(request())


def test_created_period_returns_only_contract_fields_and_trusted_actor(setup):
    """Не теряет 201, серверный request_id и доверенного инициатора события."""
    response = put(setup.app, headers={**HEADERS, "X-Request-ID": "untrusted"})
    assert response.status_code == 201
    assert response.json() == {
        "id": 123,
        "student_id": str(STUDENT),
        "class_id": 10,
        "joined_at": "2026-10-15T00:00:00Z",
        "left_at": None,
    }
    event = setup.uow.outbox.add_event.await_args.args[0]
    assert event.actor_id == "42"
    assert event.request_id == response.headers["x-request-id"]
    assert event.request_id != "untrusted"
    assert (
        "/internal/students/{student_id}/current-class-period"
        not in setup.app.openapi()["paths"]
    )


@pytest.mark.parametrize(("current_class", "expected"), [(10, 200), (20, 409)])
def test_existing_period_is_noop_or_conflict(setup, current_class, expected):
    """Другой класс не превращается в ложный успешный no-op."""
    setup.uow.class_periods.get_current_period_for_student.return_value = (
        StudentClassPeriod(
            STUDENT, current_class, id=456, joined_at=datetime(2026, 10, 15, tzinfo=UTC)
        )
    )
    response = put(setup.app)
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["id"] == 456
    setup.uow.class_periods.create_period.assert_not_awaited()
    setup.uow.outbox.add_event.assert_not_awaited()


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("missing_user", 404),
        ("missing_class", 404),
        ("teacher", 422),
        ("inactive", 422),
        ("unavailable", 503),
        ("unexpected", 500),
    ],
)
def test_business_errors_have_safe_envelope(setup, case, status):
    """Не отдаёт токен, SQL и текст инфраструктурной ошибки клиенту."""
    if case == "missing_user":
        setup.reader.get_user.return_value = None
    elif case == "missing_class":
        setup.uow.classes.get_class_by_id.return_value = None
    elif case in {"teacher", "inactive"}:
        setup.reader.get_user.return_value = GatewayUserInfo(
            id=STUDENT,
            role="teacher" if case == "teacher" else "student",
            is_active=case != "inactive",
        )
    elif case == "unavailable":
        setup.reader.get_user.side_effect = UserLookupUnavailableError(
            "secret SQL test-token"
        )
    else:
        setup.uow.class_periods.create_period.side_effect = RuntimeError(
            "secret SQL test-token"
        )
    response = put(setup.app)
    assert response.status_code == status
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "SQL" not in response.text and "test-token" not in response.text
    setup.uow.outbox.add_event.assert_not_awaited()
    if case in {"missing_user", "teacher", "inactive", "unavailable"}:
        setup.factory.assert_not_called()


@pytest.mark.parametrize(
    "actor", [None, "", "0", "042", "-1", "abc", "9223372036854775808"]
)
def test_invalid_actor_never_reaches_gateway_or_uow(setup, actor):
    """Без валидного ID сотрудника действие не начинается."""
    headers = {"Authorization": "Bearer test-token"}
    if actor is not None:
        headers["X-Actor-ID"] = actor
    assert put(setup.app, headers=headers).status_code == 422
    setup.factory.assert_not_called()
    setup.reader.get_user.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"class_id": True},
        {"class_id": "10"},
        {"class_id": 0},
        {"class_id": 2147483648},
        {"class_id": 10, "actor_id": "99"},
        {"class_id": 10, "joined_at": "2026-10-15"},
        {"class_id": 10, "actor_source": "gateway"},
    ],
)
def test_invalid_body_never_reaches_gateway_or_uow(setup, body):
    """Строгий class_id и запрет лишних полей защищают контракт записи."""
    assert put(setup.app, body=body).status_code == 422
    setup.factory.assert_not_called()
    setup.reader.get_user.assert_not_awaited()


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-Actor-ID": "42"}, {"Authorization": "Bearer wrong", "X-Actor-ID": "42"}],
)
def test_actor_does_not_replace_service_authentication(setup, headers):
    """Знание ID сотрудника не даёт доступа без служебного секрета."""
    response = put(setup.app, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    setup.factory.assert_not_called()
    setup.reader.get_user.assert_not_awaited()


@pytest.mark.parametrize(
    ("name", "permissions"),
    [
        ("backoffice", frozenset({"classes:write"})),
        ("other-service", frozenset({"class-periods:write"})),
    ],
)
def test_wrong_permission_or_service_is_forbidden(setup, name, permissions):
    """Право записи и доверенное имя сервиса проверяются независимо."""
    setup.app.dependency_overrides[get_authenticated_service] = lambda: (
        ServicePrincipal(service_name=name, permissions=permissions)
    )
    assert put(setup.app).status_code == 403
    setup.factory.assert_not_called()
    setup.reader.get_user.assert_not_awaited()


def test_unconfigured_reader_disables_only_new_write_endpoint(setup):
    """Старый live доступен, но без проверки Gateway запись запрещена."""
    app = create_app(setup.settings, setup.factory)
    response = put(app)
    assert response.status_code == 503
    setup.factory.assert_not_called()
