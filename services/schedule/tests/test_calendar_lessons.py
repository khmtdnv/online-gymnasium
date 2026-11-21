"""Личный календарь не смешивает школьные границы с прежними датами UTC."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError


def test_range_keeps_aware_school_midnight():
    from schedule_service.application.calendar_lessons import CalendarLessonsQuery

    query = CalendarLessonsQuery(
        class_id=7,
        starts_at_from="2026-10-19T00:00:00+05:00",
        starts_at_until="2026-10-25T00:00:00+05:00",
    )
    assert query.starts_at_from.hour == 0
    assert query.starts_at_from.utcoffset().total_seconds() == 18000
    for extra in (
        {"teacher_id": "00000000-0000-0000-0000-000000000001"},
        {"class_id": None},
        {"starts_at_until": "2026-10-19T00:00:00+05:00"},
        {"starts_at_until": "2026-12-19T00:00:00+05:00"},
    ):
        with pytest.raises(ValidationError):
            CalendarLessonsQuery(**(query.model_dump() | extra))


def test_route_has_private_access_and_never_silently_truncates():
    from schedule_service.api.calendar_lessons import router

    repository = SimpleNamespace(list_calendar_lessons=AsyncMock(return_value=[]))

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(lessons=repository)

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        gateway_service_token="gateway-only", homework_service_token="homework-only"
    )
    app.state.uow_factory = uow
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            params = {
                "class_id": 7,
                "starts_at_from": "2026-10-19T00:00:00+05:00",
                "starts_at_until": "2026-10-25T00:00:00+05:00",
            }
            assert (
                await client.get("/internal/calendar-lessons", params=params)
            ).status_code == 401
            response = await client.get(
                "/internal/calendar-lessons",
                params=params,
                headers={"Authorization": "Bearer homework-only"},
            )
            assert response.status_code == 200 and response.json() == []
            assert repository.list_calendar_lessons.await_args.kwargs[
                "starts_at_from"
            ] == datetime.fromisoformat(params["starts_at_from"])
            repository.list_calendar_lessons.return_value = [object()] * 1001
            response = await client.get(
                "/internal/calendar-lessons",
                params=params,
                headers={"Authorization": "Bearer gateway-only"},
            )
            assert response.status_code == 422
            assert "period" in response.text.lower()

    asyncio.run(run())


def test_internal_subjects_requires_service_token_and_lists_all():
    from schedule_service.api.calendar_lessons import router
    from schedule_service.domain.subject import Subject

    repository = SimpleNamespace(
        list_all=AsyncMock(return_value=[Subject(id=1, name="Математика")])
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(subjects=repository)

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        gateway_service_token="gateway-only", homework_service_token="homework-only"
    )
    app.state.uow_factory = uow
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/internal/subjects")).status_code == 401
            response = await client.get(
                "/internal/subjects",
                headers={"Authorization": "Bearer gateway-only"},
            )
            assert response.status_code == 200
            assert response.json() == [{"id": 1, "name": "Математика"}]

    asyncio.run(run())
