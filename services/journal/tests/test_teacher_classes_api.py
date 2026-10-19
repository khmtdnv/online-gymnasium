"""Закрытый HTTP-контракт назначений и проверка служебных прав."""

import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from journal_service.config import JournalSettings

PATH = "/internal/teachers/8df96b7a-7d30-44e7-b577-f6581300e101/classes/7"


def request(
    method="PUT",
    *,
    token="token",
    actor="42",
    created=True,
    error=None,
    principal=None,
    path=PATH,
):
    from journal_service.api.dependencies import (
        get_assign_teacher_handler,
        get_authenticated_service,
        get_teacher_classes_handler,
        get_unassign_teacher_handler,
    )
    from journal_service.app import create_app
    from journal_service.application.teacher_classes import AssignTeacherToClassResult

    app = create_app(
        JournalSettings(
            database_url="postgresql+asyncpg://test/test",
            backoffice_service_token="token",
            _env_file=None,
        ),
        Mock(),
    )
    assign = Mock(
        handle=AsyncMock(
            return_value=AssignTeacherToClassResult(created=created), side_effect=error
        )
    )
    remove = Mock(handle=AsyncMock())
    listing = Mock(handle=AsyncMock(return_value=[]))
    app.dependency_overrides[get_assign_teacher_handler] = lambda: assign
    app.dependency_overrides[get_unassign_teacher_handler] = lambda: remove
    app.dependency_overrides[get_teacher_classes_handler] = lambda: listing
    if principal is not None:
        app.dependency_overrides[get_authenticated_service] = lambda: principal

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {}
            if token is not None:
                headers["Authorization"] = "Bearer " + token
            if actor is not None:
                headers["X-Actor-ID"] = actor
            return await client.request(method, path, headers=headers)

    return asyncio.run(run()), assign, remove


@pytest.mark.parametrize("created,status", [(True, 201), (False, 204)])
def test_put_is_empty_201_or_204(created, status):
    response, _, _ = request(created=created)
    assert response.status_code == status
    assert response.content == b""


def test_delete_and_list_do_not_require_gateway_lookup():
    assert request("DELETE")[0].status_code == 204
    response, _, _ = request("GET", actor=None, path=PATH.rsplit("/", 1)[0])
    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize(
    "token,actor,status",
    [
        (None, "42", 401),
        ("bad", "42", 401),
        ("token", None, 422),
        ("token", "0", 422),
        ("token", "9223372036854775808", 422),
    ],
)
def test_invalid_credentials_or_actor_cannot_write(token, actor, status):
    response, handler, _ = request(token=token, actor=actor)
    assert response.status_code == status
    handler.handle.assert_not_awaited()


def test_write_requires_specific_permission_and_backoffice_identity():
    from journal_service.api.dependencies import ServicePrincipal

    for name, permissions in [
        ("backoffice", frozenset({"classes:write"})),
        ("other", frozenset({"teacher-classes:write"})),
    ]:
        response, handler, _ = request(
            principal=ServicePrincipal(service_name=name, permissions=permissions)
        )
        assert response.status_code == 403
        handler.handle.assert_not_awaited()


@pytest.mark.parametrize(
    "kind,status",
    [
        ("TeacherNotFoundError", 404),
        ("InvalidTeacherError", 422),
        ("ClassNotFoundError", 404),
        ("UserLookupUnavailableError", 503),
    ],
)
def test_expected_errors_have_safe_statuses(kind, status):
    from journal_service.application.ports import errors

    assert request(error=getattr(errors, kind)())[0].status_code == status


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", PATH.rsplit("/", 1)[0] + "/0"),
        ("PUT", PATH.replace("8df96b7a-7d30-44e7-b577-f6581300e101", "bad")),
        ("GET", PATH.rsplit("/", 1)[0] + "?limit=101"),
        ("GET", PATH.rsplit("/", 1)[0] + "?offset=-1"),
    ],
)
def test_invalid_identifiers_and_pagination_are_rejected(method, path):
    response, assign, _ = request(method, path=path)
    assert response.status_code == 422
    assign.handle.assert_not_awaited()


def test_read_permission_is_separate_from_class_write():
    from journal_service.api.dependencies import ServicePrincipal

    response, _, _ = request(
        "GET",
        path=PATH.rsplit("/", 1)[0],
        principal=ServicePrincipal(
            service_name="backoffice", permissions=frozenset({"classes:write"})
        ),
    )
    assert response.status_code == 403
