"""Homework имеет чтение конкретной пары, но не права Backoffice."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from sqlalchemy.exc import OperationalError

PATH = "/internal/teachers/00000000-0000-0000-0000-000000000001/classes/7"


def request(
    *, token="homework-only", method="GET", assigned=True, failure=None, ambiguous=False
):
    from journal_service.app import create_app
    from journal_service.config import JournalSettings

    repo = SimpleNamespace(
        is_assigned=AsyncMock(return_value=assigned, side_effect=failure)
    )

    class Context:
        async def __aenter__(self):
            return SimpleNamespace(teacher_classes=repo)

        async def __aexit__(self, *args):
            return None

    app = create_app(
        JournalSettings(
            database_url="test",
            backoffice_service_token="backoffice",
            homework_service_token="backoffice" if ambiguous else "homework-only",
            _env_file=None,
        ),
        Context,
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-Actor-ID": "42", "X-Service-Name": "backoffice"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            return await client.request(method, PATH, headers=headers)

    return asyncio.run(run())


def test_exact_assignment_read_and_confirmed_absence():
    response = request()
    assert response.status_code == 200
    assert response.json() == {"teacher_id": str(UUID(int=1)), "class_id": 7}
    assert request(assigned=False).status_code == 404


@pytest.mark.parametrize("token", [None, "bad"])
def test_missing_or_invalid_token_cannot_read(token):
    assert request(token=token).status_code == 401


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_homework_cannot_modify_assignment_even_with_actor(method):
    assert request(method=method).status_code == 403


def test_backoffice_still_can_read_assignment():
    assert request(token="backoffice").status_code == 200


def test_ambiguous_service_secrets_fail_closed():
    assert request(token="backoffice", ambiguous=True).status_code == 503


@pytest.mark.parametrize(
    "failure",
    [
        OperationalError("SELECT", {}, RuntimeError("secret")),
        ConnectionRefusedError("secret"),
        TimeoutError("secret"),
    ],
)
def test_database_failure_is_not_assignment_absence(failure):
    response = request(failure=failure)
    assert response.status_code == 503
    assert "secret" not in response.text


def test_repository_uses_both_pair_identifiers():
    from sqlalchemy.dialects import postgresql

    from journal_service.infrastructure.teacher_class_repository import (
        SqlAlchemyTeacherClassRepository,
    )

    seen = []

    async def scalar(stmt):
        seen.append(
            str(
                stmt.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
        )
        return False

    assert (
        asyncio.run(
            SqlAlchemyTeacherClassRepository(
                SimpleNamespace(scalar=scalar)
            ).is_assigned(UUID(int=1), 7)
        )
        is False
    )
    assert "class_id = 7" in seen[0]
    assert "teacher_id = '00000000-0000-0000-0000-000000000001'" in seen[0]
