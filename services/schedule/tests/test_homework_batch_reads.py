"""Пакетное чтение использует тот же служебный доступ и не пишет уроки."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from schedule_service.domain.lesson import Lesson


def request(payload, *, token="hw", configured=True, empty=False, failure=None):
    from schedule_service.api.homework_reads import router

    rows = (
        []
        if empty
        else [
            Lesson(
                id=i,
                class_id=7,
                subject_id=3,
                teacher_id=UUID(int=1),
                starts_at=datetime(2026, 10, 18, i, tzinfo=UTC),
                ends_at=datetime(2026, 10, 18, i, 45, tzinfo=UTC),
                status="canceled" if i == 12 else "planned",
            )
            for i in [11, 12]
        ]
    )

    async def get_many(ids):
        assert ids == [12, 11, 99]
        if failure:
            raise failure
        return rows

    class Context:
        async def __aenter__(self):
            return SimpleNamespace(lessons=SimpleNamespace(get_many=get_many))

        async def __aexit__(self, *args):
            pass

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        homework_service_token="hw" if configured else None
    )
    app.state.uow_factory = Context
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://schedule"
        ) as client:
            response = await client.post(
                "/internal/lessons/lookup",
                json=payload,
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            assert (
                "/internal/lessons/lookup"
                not in (await client.get("/openapi.json")).json()["paths"]
            )
            return response

    return asyncio.run(run())


def test_batch_returns_existing_lessons_including_canceled():
    response = request({"lesson_ids": [12, 11, 99]})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [11, 12]
    assert response.json()[1]["status"] == "canceled"
    assert request({"lesson_ids": [12, 11, 99]}, empty=True).json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"lesson_ids": []},
        {"lesson_ids": list(range(1, 102))},
        {"lesson_ids": [11, 11]},
        {"lesson_ids": [True]},
        {"lesson_ids": ["11"]},
        {"lesson_ids": [0]},
        {"lesson_ids": [2147483648]},
        {"lesson_ids": [11], "extra": 1},
    ],
)
def test_invalid_batch_is_rejected(payload):
    assert request(payload).status_code == 422


@pytest.mark.parametrize("token", [None, "bad"])
def test_batch_requires_service_token(token):
    assert request({"lesson_ids": [12, 11, 99]}, token=token).status_code == 401


def test_batch_configuration_and_database_failure_are_503():
    assert request({"lesson_ids": [12, 11, 99]}, configured=False).status_code == 503
    response = request(
        {"lesson_ids": [12, 11, 99]}, failure=ConnectionRefusedError("secret")
    )
    assert response.status_code == 503
    assert "secret" not in response.text
