"""Проверяет завершение и его гонку с переводом через настоящие транзакции."""

import asyncio
from unittest.mock import patch

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_transfer_student_to_class_postgres import command_for, handler_for, seed

from journal_service.application.class_periods import ClassPeriodResult
from journal_service.application.end_student_class_period import (
    EndStudentClassPeriodCommand,
    EndStudentClassPeriodHandler,
)
from journal_service.application.ports.errors import StudentClassPeriodConflictError
from journal_service.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from journal_service.infrastructure.student_class_period_repository import (
    SqlAlchemyStudentClassPeriodRepository,
)


def end_command(period):
    """Сохраняет ожидаемую версию сотрудника при повторной отправке."""
    from uuid import uuid4

    return EndStudentClassPeriodCommand(
        student_id=period.student_id,
        expected_period_id=period.id,
        actor_id="42",
        request_id=str(uuid4()),
    )


def test_end_twice_preserves_one_closed_period_and_one_event(database_url):
    """Повтор без активного периода не перезаписывает дату и не дублирует аудит."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, _ = await seed(factory)
            handler = EndStudentClassPeriodHandler(factory)
            command = end_command(period)
            await handler.handle(command)
            async with engine.connect() as conn:
                left = await conn.scalar(
                    text("SELECT left_at FROM student_class_periods")
                )
            await handler.handle(command)
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT id,left_at FROM student_class_periods")
                    )
                ).one()
                assert row.id == period.id and row.left_at == left
                envelopes = (
                    await conn.scalars(
                        text("SELECT envelope FROM journal_event_outbox")
                    )
                ).all()
                assert len(envelopes) == 1
                assert envelopes[0]["payload"] == {
                    "operation": "removed",
                    "student_id": str(period.student_id),
                    "previous": {"period_id": period.id, "class_id": period.class_id},
                    "current": None,
                }

    asyncio.run(scenario())


def test_end_and_transfer_from_same_expected_have_one_effect(database_url):
    """Завершение не закрывает новый период, если конкурентный перевод выиграл."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, classes = await seed(factory)
            barrier = asyncio.Barrier(2)
            original = SqlAlchemyStudentClassPeriodRepository.get_period_for_update

            async def synchronized_lock(repository, student_id, period_id):
                await asyncio.wait_for(barrier.wait(), 5)
                return await original(repository, student_id, period_id)

            with patch.object(
                SqlAlchemyStudentClassPeriodRepository,
                "get_period_for_update",
                synchronized_lock,
            ):
                outcomes = await asyncio.wait_for(
                    asyncio.gather(
                        handler_for(factory, period.student_id).handle(
                            command_for(period, classes[1].id)
                        ),
                        EndStudentClassPeriodHandler(factory).handle(
                            end_command(period)
                        ),
                        return_exceptions=True,
                    ),
                    15,
                )
            assert (
                sum(
                    isinstance(item, StudentClassPeriodConflictError)
                    for item in outcomes
                )
                == 1
            ), outcomes
            transfer_won = isinstance(outcomes[0], ClassPeriodResult)
            assert (
                outcomes[1] is None
                if not transfer_won
                else isinstance(outcomes[1], StudentClassPeriodConflictError)
            )
            async with engine.connect() as conn:
                assert (
                    await conn.scalar(text("SELECT count(*) FROM journal_event_outbox"))
                    == 1
                )
                assert await conn.scalar(
                    text(
                        "SELECT count(*) FROM student_class_periods WHERE left_at IS NULL"
                    )
                ) == (1 if transfer_won else 0)
                if transfer_won:
                    assert (
                        await conn.scalar(
                            text(
                                "SELECT id FROM student_class_periods WHERE left_at IS NULL"
                            )
                        )
                        == outcomes[0].id
                    )

    asyncio.run(scenario())


def test_end_outbox_sql_failure_restores_open_period(database_url):
    """Реальный конфликт события откатывает завершение, а не только вставку outbox."""

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, _ = await seed(factory)
            original = SqlAlchemyOutboxRepository.add_event

            async def duplicate(repository, event):
                await original(repository, event)
                await original(repository, event)

            with (
                patch.object(SqlAlchemyOutboxRepository, "add_event", duplicate),
                pytest.raises(IntegrityError),
            ):
                await EndStudentClassPeriodHandler(factory).handle(end_command(period))
            async with engine.connect() as conn:
                assert (
                    await conn.scalar(text("SELECT left_at FROM student_class_periods"))
                    is None
                )
                assert (
                    await conn.scalar(text("SELECT count(*) FROM journal_event_outbox"))
                    == 0
                )

    asyncio.run(scenario())


def test_period_changes_http_flow_uses_real_storage_and_gateway_contract(database_url):
    """HTTP-перевод, stale409 и повтор завершения дают два реальных события."""
    import httpx

    from journal_service.app import create_app
    from journal_service.config import JournalSettings
    from journal_service.infrastructure.gateway_user_reader import HttpGatewayUserReader

    async def scenario():
        async with database(database_url) as (engine, factory):
            period, classes = await seed(factory)
            gateway_calls = []

            def gateway_reply(request):
                gateway_calls.append(request)
                assert request.headers["authorization"] == "Bearer lookup-token"
                assert request.url.path == f"/internal/users/{period.student_id}"
                return httpx.Response(
                    200,
                    json={
                        "id": str(period.student_id),
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
                    gateway_user_reader=HttpGatewayUserReader(outgoing, "lookup-token"),
                )
                async with (
                    app.router.lifespan_context(app),
                    httpx.AsyncClient(
                        base_url="http://journal",
                        transport=httpx.ASGITransport(app=app),
                        headers={
                            "Authorization": "Bearer test-token",
                            "X-Actor-ID": "42",
                        },
                    ) as client,
                ):
                    path = (
                        f"/internal/students/{period.student_id}/current-class-period"
                    )
                    body = {
                        "target_class_id": classes[1].id,
                        "expected_period_id": period.id,
                    }
                    moved = await client.post(path + "/transfer", json=body)
                    assert moved.status_code == 200
                    new = moved.json()
                    assert new["id"] != period.id and new["class_id"] == classes[1].id
                    assert (
                        await client.post(path + "/transfer", json=body)
                    ).status_code == 409
                    calls_before_end = len(gateway_calls)
                    for _ in range(2):
                        ended = await client.delete(
                            path, params={"expected_period_id": new["id"]}
                        )
                        assert ended.status_code == 204 and ended.content == b""
                    assert len(gateway_calls) == calls_before_end
                    assert (await client.get(path)).status_code == 404
                async with engine.connect() as conn:
                    rows = (
                        await conn.execute(
                            text(
                                "SELECT id,joined_at,left_at FROM student_class_periods ORDER BY id"
                            )
                        )
                    ).all()
                    assert len(rows) == 2
                    assert rows[0].left_at == rows[1].joined_at
                    assert rows[1].left_at is not None
                    envelopes = (
                        await conn.scalars(
                            text(
                                "SELECT envelope FROM journal_event_outbox ORDER BY created_at"
                            )
                        )
                    ).all()
                    assert [event["payload"]["operation"] for event in envelopes] == [
                        "transferred",
                        "removed",
                    ]
                    assert envelopes[0]["request_id"] == moved.headers["x-request-id"]
                    assert envelopes[1]["actor"] == {"source": "backoffice", "id": "42"}

    asyncio.run(scenario())
