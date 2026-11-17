"""Проверяет HTTP→handler→UoW→repository на отдельной PostgreSQL-БД."""

import asyncio
from uuid import UUID

import httpx
from conftest import database
from sqlalchemy import text

from journal_service.app import create_app
from journal_service.config import JournalSettings


def test_period_http_reads_use_real_transactions_and_saved_history(
    database_url: str,
) -> None:
    """Читает текущий класс, историю и состав без подмены application или БД."""

    async def run() -> None:
        async with database(database_url) as (engine, factory):
            student_id = UUID("aaaaaaaa-0000-4000-8000-000000000001")
            other_id = UUID("bbbbbbbb-0000-4000-8000-000000000002")
            missing_id = UUID("cccccccc-0000-4000-8000-000000000003")
            async with engine.begin() as connection:
                class_a = await connection.scalar(
                    text(
                        "INSERT INTO classes (name, study_year) VALUES ('7А', 2026) RETURNING id"
                    )
                )
                class_b = await connection.scalar(
                    text(
                        "INSERT INTO classes (name, study_year) VALUES ('7Б', 2026) RETURNING id"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO student_class_periods (id, student_id, class_id, joined_at, left_at) VALUES "
                        "(10, :student, :class_a, '2026-09-01T09:00:00Z', '2026-10-01T09:00:00Z'), "
                        "(20, :student, :class_b, '2026-10-01T09:00:00Z', NULL), "
                        "(30, :other, :class_b, '2026-10-01T09:00:00Z', NULL)"
                    ),
                    {
                        "student": student_id,
                        "other": other_id,
                        "class_a": class_a,
                        "class_b": class_b,
                    },
                )
            app = create_app(
                JournalSettings(
                    database_url=database_url,
                    backoffice_service_token="test-token",
                    _env_file=None,
                ),
                factory,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": "Bearer test-token"},
            ) as client:
                current = await client.get(
                    f"/internal/students/{student_id}/current-class-period"
                )
                assert current.status_code == 200
                assert current.json() == {
                    "id": 20,
                    "student_id": str(student_id),
                    "class_id": class_b,
                    "joined_at": "2026-10-01T09:00:00Z",
                    "left_at": None,
                }
                history = await client.get(
                    f"/internal/students/{student_id}/class-periods"
                )
                assert history.status_code == 200
                assert [period["id"] for period in history.json()] == [10, 20]
                assert history.json()[0]["left_at"] == "2026-10-01T09:00:00Z"
                page = await client.get(
                    f"/internal/students/{student_id}/class-periods",
                    params={"limit": 1, "offset": 1},
                )
                assert [period["id"] for period in page.json()] == [20]
                roster = await client.get(
                    f"/internal/classes/{class_b}/current-periods"
                )
                assert roster.status_code == 200
                assert [period["id"] for period in roster.json()] == [20, 30]
                empty_class = await client.get(
                    f"/internal/classes/{class_a}/current-periods"
                )
                assert empty_class.status_code == 200
                assert empty_class.json() == []
                missing_class = await client.get(
                    "/internal/classes/2147483647/current-periods"
                )
                assert missing_class.status_code == 404
                missing_current = await client.get(
                    f"/internal/students/{missing_id}/current-class-period"
                )
                assert missing_current.status_code == 404
                empty_history = await client.get(
                    f"/internal/students/{missing_id}/class-periods"
                )
                assert empty_history.status_code == 200
                assert empty_history.json() == []

    asyncio.run(run())
