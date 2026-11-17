"""HTTP-чтение назначения проверяется вместе с настоящим SQL EXISTS."""

import asyncio
from uuid import UUID

import httpx
from conftest import database
from sqlalchemy import text


def test_exact_pair_real_database_and_homework_cannot_write(database_url):
    from journal_service.app import create_app
    from journal_service.config import JournalSettings

    async def run():
        async with database(database_url) as (engine, factory):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO classes(id,name,study_year) VALUES (7,'7А',2026),(8,'7Б',2026)"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO teacher_classes(teacher_id,class_id) VALUES (:teacher,7)"
                    ),
                    {"teacher": UUID(int=1)},
                )
            app = create_app(
                JournalSettings(
                    database_url=database_url,
                    backoffice_service_token="test-backoffice",
                    homework_service_token="test-homework",
                    _env_file=None,
                ),
                factory,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://journal"
            ) as client:
                path = f"/internal/teachers/{UUID(int=1)}/classes/7"
                headers = {"Authorization": "Bearer test-homework", "X-Actor-ID": "42"}
                assert (await client.get(path, headers=headers)).status_code == 200
                assert (
                    await client.get(path.replace("/7", "/8"), headers=headers)
                ).status_code == 404
                assert (
                    await client.get(
                        path.replace(str(UUID(int=1)), str(UUID(int=2))),
                        headers=headers,
                    )
                ).status_code == 404
                assert (await client.put(path, headers=headers)).status_code == 403
                response = await client.post(
                    "/internal/classes",
                    json={"name": "9А", "study_year": 2026},
                    headers=headers,
                )
                assert response.status_code == 403

    asyncio.run(run())
