"""Homework читает текущий класс, но не историю/составы/запись."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from journal_service.app import create_app
from journal_service.config import JournalSettings
from journal_service.domain.student_class_period import StudentClassPeriod

STUDENT = UUID(int=1)
CURRENT = f"/internal/students/{STUDENT}/current-class-period"


def request(path=CURRENT, token="hw", *, method="GET", absent=False, failure=None):
    period = (
        None
        if absent
        else StudentClassPeriod(
            student_id=STUDENT,
            class_id=7,
            id=1,
            joined_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    repo = SimpleNamespace(
        get_current_period_for_student=AsyncMock(
            return_value=period,
            side_effect=failure,
        )
    )

    class Context:
        async def __aenter__(self):
            return SimpleNamespace(class_periods=repo)

        async def __aexit__(self, *args):
            pass

    app = create_app(
        JournalSettings(
            database_url="test",
            backoffice_service_token="bo",
            homework_service_token="hw",
            _env_file=None,
        ),
        Context,
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://journal"
        ) as client:
            headers = (
                {"Authorization": f"Bearer {token}", "X-Actor-ID": "42"}
                if token
                else {}
            )
            return await client.request(method, path, headers=headers)

    return asyncio.run(run())


@pytest.mark.parametrize("token", ["hw", "bo"])
def test_homework_and_backoffice_can_read_current_period(token):
    response = request(token=token)
    assert response.status_code == 200
    assert response.json()["student_id"] == str(STUDENT)
    assert response.json()["class_id"] == 7


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (f"/internal/students/{STUDENT}/class-periods", "GET"),
        ("/internal/classes/7/current-periods", "GET"),
        (CURRENT, "PUT"),
        (CURRENT, "DELETE"),
    ],
)
def test_homework_has_no_history_roster_or_write_permission(path, method):
    assert request(path, method=method).status_code == 403


@pytest.mark.parametrize("token", [None, "bad"])
def test_service_token_required(token):
    assert request(token=token).status_code == 401


def test_absence_is_distinct_from_database_failure():
    assert request(absent=True).status_code == 404
    response = request(failure=ConnectionRefusedError("secret"))
    assert response.status_code == 503
    assert "secret" not in response.text
