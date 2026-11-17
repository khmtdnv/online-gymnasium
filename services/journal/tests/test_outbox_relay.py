"""Relay не помечает событие опубликованным до подтверждения брокера."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest


def test_journal_relay_failure_keeps_event_pending():
    from journal_service.application.outbox_relay import OutboxRelay

    event = {"event_id": str(UUID(int=1)), "payload": {"student_id": str(UUID(int=2))}}
    outbox = SimpleNamespace(
        get_pending=AsyncMock(return_value=[event]),
        mark_published=AsyncMock(),
    )

    @asynccontextmanager
    async def uow():
        yield SimpleNamespace(outbox=outbox)

    async def run():
        publish = AsyncMock(side_effect=RuntimeError("Kafka offline"))
        with pytest.raises(RuntimeError, match="Kafka offline"):
            await OutboxRelay(uow, publish).run_once()
        outbox.mark_published.assert_not_awaited()
        publish.side_effect = None
        assert await OutboxRelay(uow, publish).run_once() == 1
        outbox.mark_published.assert_awaited_once_with(UUID(int=1))

    asyncio.run(run())
