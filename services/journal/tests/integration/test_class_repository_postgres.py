"""Проверяет реальные транзакции и HTTP на отдельной тестовой PostgreSQL-БД."""

import asyncio

import httpx
import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from journal_service.app import create_app
from journal_service.application.ports.errors import DuplicateClassError
from journal_service.config import JournalSettings
from journal_service.domain.school_class import Class
from journal_service.infrastructure.database import (
    check_database,
)


def test_real_commit_and_rollback(database_url: str) -> None:
    """Сохраняет commit между сессиями и отменяет вставку при исключении."""

    async def run():
        async with database(database_url) as (_, factory):
            async with factory() as uow:
                saved = await uow.classes.create_class(
                    Class(name="7А", study_year=2026)
                )
            with pytest.raises(RuntimeError, match="rollback"):
                async with factory() as uow:
                    await uow.classes.create_class(Class(name="7Б", study_year=2026))
                    raise RuntimeError("rollback")
            async with factory() as uow:
                rows = await uow.classes.list_classes(None, 50, 0)
            assert [row.id for row in rows] == [saved.id]
            assert saved.created_at.tzinfo is not None

    asyncio.run(run())


def test_real_duplicate_filter_order_and_pagination(database_url: str) -> None:
    """Проверяет именованный конфликт, разные годы и чтение страниц по ID."""

    async def run():
        async with database(database_url) as (_, factory):
            saved = []
            for name, year in [(" 7А ", 2026), ("7А", 2027), ("7Б", 2026)]:
                async with factory() as uow:
                    saved.append(
                        await uow.classes.create_class(
                            Class(name=name, study_year=year)
                        )
                    )
            with pytest.raises(DuplicateClassError):
                async with factory() as uow:
                    await uow.classes.create_class(Class(name=" 7А ", study_year=2026))
            async with factory() as uow:
                filtered = await uow.classes.list_classes(2026, 50, 0)
                page = await uow.classes.list_classes(None, 1, 1)
                empty = await uow.classes.list_classes(2025, 50, 0)
            assert [(row.name, row.id) for row in filtered] == [
                ("7А", saved[0].id),
                ("7Б", saved[2].id),
            ]
            assert [row.id for row in page] == [saved[1].id]
            assert empty == []

    asyncio.run(run())


def test_concurrent_creation_has_one_success_and_one_conflict(
    database_url: str,
) -> None:
    """Доказывает уникальность пары при двух независимых конкурентных транзакциях."""

    async def run():
        async with database(database_url) as (_, factory):
            start = asyncio.Event()

            async def create():
                await start.wait()
                async with factory() as uow:
                    return await uow.classes.create_class(
                        Class(name="8А", study_year=2026)
                    )

            tasks = [asyncio.create_task(create()), asyncio.create_task(create())]
            start.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert sum(isinstance(result, Class) for result in results) == 1
            assert (
                sum(isinstance(result, DuplicateClassError) for result in results) == 1
            )
            async with factory() as uow:
                assert len(await uow.classes.list_classes(None, 50, 0)) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    ("name", "year", "constraint"),
    [
        ("", 2026, "classes_valid_name"),
        (" 7А", 2026, "classes_valid_name"),
        ("7А", 1899, "classes_valid_study_year"),
        ("7А", 9999, "classes_valid_study_year"),
    ],
)
def test_database_enforces_checks_without_domain(
    database_url: str, name: str, year: int, constraint: str
) -> None:
    """Доказывает, что прямой SQL не обходит ограничения имени и года."""

    async def run():
        async with database(database_url) as (engine, _):
            with pytest.raises(IntegrityError) as caught:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO classes (name, study_year) VALUES (:name, :year)"
                        ),
                        {"name": name, "year": year},
                    )
            assert caught.value.driver_exception.sqlstate == "23514"
            assert caught.value.driver_exception.constraint_name == constraint

    asyncio.run(run())


def test_http_flow_with_real_database(database_url: str) -> None:
    """Проводит запросы через HTTP, прикладные обработчики, UoW и PostgreSQL."""

    async def run():
        async with database(database_url) as (engine, factory):
            settings = JournalSettings(
                database_url=database_url,
                backoffice_service_token="test-token",
                _env_file=None,
            )

            async def ready():
                await check_database(engine)

            app = create_app(settings, factory, readiness_check=ready)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                headers = {"Authorization": "Bearer test-token"}
                assert (await client.get("/health/ready")).status_code == 200
                assert (await client.get("/internal/classes")).status_code == 401
                payload = {"name": " 9А ", "study_year": 2026}
                created = await client.post(
                    "/internal/classes", json=payload, headers=headers
                )
                assert created.status_code == 201
                assert created.json()["name"] == "9А"
                listed = await client.get(
                    "/internal/classes?study_year=2026", headers=headers
                )
                assert listed.json() == [created.json()]
                duplicate = await client.post(
                    "/internal/classes", json=payload, headers=headers
                )
                assert duplicate.status_code == 409
                invalid = await client.post(
                    "/internal/classes",
                    json={"name": " ", "study_year": 2026},
                    headers=headers,
                )
                assert invalid.status_code == 422
                nul = await client.post(
                    "/internal/classes",
                    json={"name": "7\x00А", "study_year": 2026},
                    headers=headers,
                )
                assert nul.status_code == 422
                excessive_offset = await client.get(
                    "/internal/classes", params={"offset": 2**63}, headers=headers
                )
                assert excessive_offset.status_code == 422
                assert (await client.get("/health/ready")).status_code == 200

    asyncio.run(run())
