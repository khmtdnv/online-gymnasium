"""Проверяет PUT → Gateway reader → обработчик → PostgreSQL → outbox."""

import asyncio
from uuid import uuid4

import httpx
from conftest import database
from sqlalchemy import text

from journal_service.app import create_app
from journal_service.config import JournalSettings
from journal_service.domain.school_class import Class
from journal_service.infrastructure.gateway_user_reader import HttpGatewayUserReader


def test_add_student_http_flow_uses_real_storage_and_gateway_contract(database_url):
    """Добавление, повтор, конфликт и сбой Gateway сохраняют правильные эффекты."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            async with factory() as uow:
                first = await uow.classes.create_class(Class("8А", 2026))
                second = await uow.classes.create_class(Class("8Б", 2026))
            student = uuid4()
            unavailable = False

            def gateway_reply(request):
                assert request.headers["authorization"] == "Bearer gateway-reader-token"
                if unavailable:
                    return httpx.Response(503, text="private upstream details")
                assert request.url.path == f"/internal/users/{student}"
                return httpx.Response(
                    200,
                    json={
                        "id": str(student),
                        "role": "student",
                        "is_active": True,
                    },
                )

            async with httpx.AsyncClient(
                base_url="http://gateway", transport=httpx.MockTransport(gateway_reply)
            ) as outgoing:
                app = create_app(
                    JournalSettings(
                        database_url=database_url,
                        backoffice_service_token="test-token",
                        _env_file=None,
                    ),
                    factory,
                    gateway_user_reader=HttpGatewayUserReader(
                        outgoing, "gateway-reader-token"
                    ),
                )
                async with (
                    app.router.lifespan_context(app),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url="http://journal",
                        headers={
                            "Authorization": "Bearer test-token",
                            "X-Actor-ID": "42",
                        },
                    ) as client,
                ):
                    path = f"/internal/students/{student}/current-class-period"
                    created = await client.put(path, json={"class_id": first.id})
                    assert created.status_code == 201
                    period = created.json()
                    assert set(period) == {
                        "id",
                        "student_id",
                        "class_id",
                        "joined_at",
                        "left_at",
                    }
                    assert period["student_id"] == str(student)
                    assert period["class_id"] == first.id
                    assert period["left_at"] is None
                    current = await client.get(path)
                    assert current.status_code == 200 and current.json() == period
                    repeated = await client.put(path, json={"class_id": first.id})
                    assert repeated.status_code == 200 and repeated.json() == period
                    conflict = await client.put(path, json={"class_id": second.id})
                    assert conflict.status_code == 409
                    unavailable = True
                    failed = await client.put(
                        f"/internal/students/{uuid4()}/current-class-period",
                        json={"class_id": second.id},
                    )
                    assert failed.status_code == 503
                    assert "upstream" not in failed.text
                assert not outgoing.is_closed
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM student_class_periods")
                    )
                    == 1
                )
                envelope = (
                    await connection.scalars(
                        text("SELECT envelope FROM journal_event_outbox")
                    )
                ).one()
                assert envelope["event_source"] == "journal"
                assert envelope["event_type"] == "journal.student_class.changed"
                assert envelope["actor"] == {"source": "backoffice", "id": "42"}
                assert envelope["request_id"] == created.headers["x-request-id"]
                assert envelope["payload"] == {
                    "operation": "added",
                    "student_id": str(student),
                    "previous": None,
                    "current": {"period_id": period["id"], "class_id": first.id},
                }

    asyncio.run(scenario())
