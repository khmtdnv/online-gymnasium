"""Проверяет настоящую цепочку router/dependency/handler с подменой только БД."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest

from journal_service.api.dependencies import ServicePrincipal, get_authenticated_service
from journal_service.app import create_app
from journal_service.config import JournalSettings
from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod

STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
CURRENT_PATH = f"/internal/students/{STUDENT_ID}/current-class-period"
HISTORY_PATH = f"/internal/students/{STUDENT_ID}/class-periods"
ROSTER_PATH = "/internal/classes/7/current-periods"
PATHS = [CURRENT_PATH, HISTORY_PATH, ROSTER_PATH]


def make_app():
    """Собирает приложение с настоящими обработчиками и отдельным fake UoW."""
    joined_at = datetime(2026, 9, 1, 9, tzinfo=UTC)
    current = StudentClassPeriod(
        id=20, student_id=STUDENT_ID, class_id=7, joined_at=joined_at
    )
    closed = StudentClassPeriod(
        id=10, student_id=STUDENT_ID, class_id=7, joined_at=joined_at, left_at=joined_at
    )
    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.class_periods.get_current_period_for_student = AsyncMock(return_value=current)
    uow.class_periods.list_periods_for_student = AsyncMock(
        return_value=[closed, current]
    )
    uow.classes.get_class_by_id = AsyncMock(
        return_value=Class(name="7А", study_year=2026, id=7, created_at=joined_at)
    )
    uow.class_periods.list_current_periods_for_class = AsyncMock(return_value=[current])
    factory = Mock(return_value=uow)
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="test-token",
        _env_file=None,
    )
    return create_app(settings, factory), uow, factory


def request(
    app, path: str, *, token: str | None = "test-token", params: dict | None = None
):
    """Выполняет GET через ASGI, позволяя проверить безопасный ответ 500."""

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            return await client.get(path, headers=headers, params=params)

    return asyncio.run(run())


def test_current_period_has_exact_public_fields() -> None:
    """Проверяет поля DTO, UUID/даты, request ID и вызов конкретного ученика."""
    app, uow, _ = make_app()
    response = request(app, CURRENT_PATH)
    assert response.status_code == 200
    assert response.json() == {
        "id": 20,
        "student_id": str(STUDENT_ID),
        "class_id": 7,
        "joined_at": "2026-09-01T09:00:00Z",
        "left_at": None,
    }
    assert UUID(response.headers["x-request-id"]).version == 4
    uow.class_periods.get_current_period_for_student.assert_awaited_once_with(
        STUDENT_ID
    )


@pytest.mark.parametrize(
    "path,method,expected_ids",
    [
        (HISTORY_PATH, "list_periods_for_student", [10, 20]),
        (ROSTER_PATH, "list_current_periods_for_class", [20]),
    ],
)
def test_lists_preserve_order_and_pass_pagination(
    path: str, method: str, expected_ids: list[int]
) -> None:
    """Передаёт пагинацию и сохраняет поля и порядок application результата."""
    app, uow, _ = make_app()
    response = request(app, path, params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == expected_ids
    kwargs = {"student_id": STUDENT_ID} if path == HISTORY_PATH else {"class_id": 7}
    getattr(
        uow.classes if method == "get_class_by_id" else uow.class_periods, method
    ).assert_awaited_once_with(**kwargs, limit=2, offset=1)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_reads_require_service_authentication(path: str, token: str | None) -> None:
    """Не открывает UoW без правильного служебного токена."""
    app, _, factory = make_app()
    response = request(app, path, token=token)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_error"
    factory.assert_not_called()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("can_read", [True, False])
def test_reads_check_required_read_permission(path: str, can_read: bool) -> None:
    """Только право чтения достаточно; write-only не даёт доступа к периодам."""
    app, _, factory = make_app()
    required = "student-current-class:read" if path == CURRENT_PATH else "classes:read"
    permissions = frozenset({required} if can_read else {"classes:write"})
    app.dependency_overrides[get_authenticated_service] = lambda: ServicePrincipal(
        service_name="test-client", permissions=permissions
    )
    response = request(app, path)
    assert response.status_code == (200 if can_read else 403)
    if not can_read:
        factory.assert_not_called()


@pytest.mark.parametrize(
    "path,method",
    [
        (CURRENT_PATH, "get_current_period_for_student"),
        (ROSTER_PATH, "get_class_by_id"),
    ],
)
def test_missing_resource_has_safe_not_found_envelope(path: str, method: str) -> None:
    """Различает отсутствие текущего периода и неизвестный класс."""
    app, uow, _ = make_app()
    getattr(
        uow.classes if method == "get_class_by_id" else uow.class_periods, method
    ).return_value = None
    response = request(app, path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "path,method",
    [
        (HISTORY_PATH, "list_periods_for_student"),
        (ROSTER_PATH, "list_current_periods_for_class"),
    ],
)
def test_empty_list_is_success(path: str, method: str) -> None:
    """Возвращает пустой JSON-список для отсутствия истории/пустого класса."""
    app, uow, _ = make_app()
    getattr(
        uow.classes if method == "get_class_by_id" else uow.class_periods, method
    ).return_value = []
    response = request(app, path)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("path", [HISTORY_PATH, ROSTER_PATH])
@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 2**63},
        {"limit": "true"},
    ],
)
def test_invalid_page_is_rejected_before_uow(path: str, params: dict) -> None:
    """Не допускает неверные страницы до прикладного чтения."""
    app, _, factory = make_app()
    response = request(app, path, params=params)
    assert response.status_code == 422
    factory.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "/internal/students/invalid/current-class-period",
        "/internal/students/invalid/class-periods",
        "/internal/classes/0/current-periods",
        "/internal/classes/2147483648/current-periods",
    ],
)
def test_invalid_path_ids_are_rejected_before_uow(path: str) -> None:
    """Проверяет UUID и диапазон class_id на границе HTTP."""
    app, _, factory = make_app()
    assert request(app, path).status_code == 422
    factory.assert_not_called()


def test_period_routes_are_hidden_from_openapi() -> None:
    """Служебные адреса не публикуются, но защищены зависимостью независимо от этого."""
    app, _, _ = make_app()
    assert not any("period" in path for path in app.openapi()["paths"])


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (CURRENT_PATH, "get_current_period_for_student"),
        (HISTORY_PATH, "list_periods_for_student"),
        (ROSTER_PATH, "get_class_by_id"),
        (ROSTER_PATH, "list_current_periods_for_class"),
    ],
)
def test_database_error_has_safe_internal_error(path: str, method: str) -> None:
    """Не раскрывает ошибку БД через новую ручку."""
    app, uow, _ = make_app()
    getattr(
        uow.classes if method == "get_class_by_id" else uow.class_periods, method
    ).side_effect = RuntimeError("private-database-details")
    response = request(app, path)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private-database-details" not in response.text


@pytest.mark.parametrize(
    ("path", "method", "params", "limit", "offset"),
    [
        (HISTORY_PATH, "list_periods_for_student", None, 50, 0),
        (ROSTER_PATH, "list_current_periods_for_class", None, 50, 0),
        (
            HISTORY_PATH,
            "list_periods_for_student",
            {"limit": 100, "offset": 2**63 - 1},
            100,
            2**63 - 1,
        ),
        (
            ROSTER_PATH,
            "list_current_periods_for_class",
            {"limit": 100, "offset": 2**63 - 1},
            100,
            2**63 - 1,
        ),
    ],
)
def test_page_defaults_and_upper_bounds_reach_repository(
    path: str,
    method: str,
    params: dict | None,
    limit: int,
    offset: int,
) -> None:
    """Проверяет не только отказ, но и допустимые defaults и верхние границы."""
    app, uow, _ = make_app()
    response = request(app, path, params=params)
    assert response.status_code == 200
    kwargs = {"student_id": STUDENT_ID} if path == HISTORY_PATH else {"class_id": 7}
    getattr(
        uow.classes if method == "get_class_by_id" else uow.class_periods, method
    ).assert_awaited_once_with(**kwargs, limit=limit, offset=offset)
