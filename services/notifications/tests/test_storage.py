"""Реальная PG: повтор события, один самоплательщик и защита чужого прочтения."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_notification_inbox_is_idempotent_and_read_is_owned():
    from notifications_service.contracts import EventConflictError, parse_event
    from notifications_service.models import Base
    from notifications_service.storage import NotificationStore

    url = os.getenv("NOTIFICATIONS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires isolated PostgreSQL")
    assert make_url(url).database.startswith("notification_test_")
    user = uuid4()
    envelope = {
        "event_id": str(uuid4()),
        "event_source": "billing",
        "event_type": "billing.payment.succeeded",
        "schema_version": 1,
        "occurred_at": "2026-10-22T12:00:00Z",
        "request_id": None,
        "actor": {"source": "system", "id": "billing"},
        "payload": {
            "payment_id": 7,
            "order_id": 3,
            "student_id": str(user),
            "payer_id": str(user),
            "study_month": "2026-10-01",
            "amount_kopecks": 300000,
            "currency": "RUB",
            "refund_actor_id": None,
        },
    }
    event = parse_event(json.dumps(envelope).encode())

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            store = NotificationStore(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            assert sorted(
                await asyncio.gather(store.record(event), store.record(event))
            ) == [False, True]
            assert await store.unread_count(user) == 1
            rows = await store.list_for(user, 50, 0)
            assert len(rows) == 1 and rows[0].recipient_id == user
            assert rows[0].link == "/billing"
            assert not await store.mark_read(rows[0].id, uuid4())
            assert await store.unread_count(user) == 1
            assert await store.mark_read(rows[0].id, user)
            first_read = (await store.list_for(user, 50, 0))[0].read_at
            assert await store.mark_read(rows[0].id, user)
            assert (await store.list_for(user, 50, 0))[0].read_at == first_read
            assert await store.unread_count(user) == 0
            changed = envelope | {"payload": envelope["payload"] | {"payment_id": 8}}
            with pytest.raises(EventConflictError):
                await store.record(parse_event(json.dumps(changed).encode()))
            assert len(await store.list_for(user, 50, 0)) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())
