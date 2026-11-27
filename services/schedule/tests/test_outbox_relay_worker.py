import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Self
from unittest.mock import ANY, AsyncMock, Mock

import pytest
from aiokafka import AIOKafkaProducer
from sqlalchemy.ext.asyncio import AsyncEngine


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        database_url="postgresql+asyncpg://schedule:password@postgres:5432/schedule",
        kafka_bootstrap_servers="kafka:19092",
        schedule_snapshot_topic="schedule.lessons.v2",
        batch_size=500,
        published_retention_days=7,
        retention_interval_seconds=3600.0,
    )


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    relay: object,
    producer: AsyncMock,
    engine: AsyncMock,
    settings: SimpleNamespace,
) -> Mock:
    from schedule_service.workers import outbox_relay

    relay_factory = Mock(return_value=relay)

    monkeypatch.setattr(outbox_relay, "RelaySettings", lambda: settings)
    monkeypatch.setattr(outbox_relay, "create_engine", lambda url: engine)
    monkeypatch.setattr(outbox_relay, "create_session_factory", lambda _: object())
    monkeypatch.setattr(outbox_relay, "AIOKafkaProducer", lambda **_: producer)
    monkeypatch.setattr(outbox_relay, "OutboxRelay", relay_factory)

    return relay_factory


@pytest.mark.anyio
async def test_worker_starts_and_stops_kafka_and_database_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from schedule_service.workers import outbox_relay

    producer = AsyncMock(spec=AIOKafkaProducer)
    engine = AsyncMock(spec=AsyncEngine)
    relay = AsyncMock()
    relay.run_once.return_value = 0
    relay_factory = _configure(
        monkeypatch,
        relay=relay,
        producer=producer,
        engine=engine,
        settings=_settings(),
    )
    monkeypatch.setattr(outbox_relay, "_monotonic", lambda: 0.0)

    async def stop_loop(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(outbox_relay.asyncio, "sleep", stop_loop)

    with pytest.raises(asyncio.CancelledError):
        await outbox_relay.run()

    relay_factory.assert_called_once_with(
        uow_factory=ANY,
        publisher=ANY,
        batch_size=500,
    )
    producer.start.assert_awaited_once()
    producer.stop.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.anyio
async def test_worker_deletes_retained_events_once_per_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from schedule_service.workers import outbox_relay

    producer = AsyncMock(spec=AIOKafkaProducer)
    engine = AsyncMock(spec=AsyncEngine)
    relay = AsyncMock()
    relay.run_once.return_value = 0
    _configure(
        monkeypatch,
        relay=relay,
        producer=producer,
        engine=engine,
        settings=_settings(),
    )
    retention = AsyncMock(return_value=0)
    monkeypatch.setattr(outbox_relay, "_delete_retained_events", retention)
    clock = [0.0, 3600.0, 3600.0]
    monkeypatch.setattr(outbox_relay, "_monotonic", lambda: clock.pop(0))

    async def stop_loop(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(outbox_relay.asyncio, "sleep", stop_loop)

    with pytest.raises(asyncio.CancelledError):
        await outbox_relay.run()

    retention.assert_awaited_once()
    session_factory_arg, days_arg = retention.await_args.args
    assert days_arg == 7
    assert session_factory_arg is not None


@pytest.mark.anyio
async def test_worker_survives_retention_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from schedule_service.workers import outbox_relay

    producer = AsyncMock(spec=AIOKafkaProducer)
    engine = AsyncMock(spec=AsyncEngine)
    relay = AsyncMock()
    relay.run_once.return_value = 0
    _configure(
        monkeypatch,
        relay=relay,
        producer=producer,
        engine=engine,
        settings=_settings(),
    )
    retention = AsyncMock(side_effect=RuntimeError("Database is unavailable"))
    monkeypatch.setattr(outbox_relay, "_delete_retained_events", retention)
    clock = [0.0, 3600.0, 3600.0]
    monkeypatch.setattr(outbox_relay, "_monotonic", lambda: clock.pop(0))

    async def stop_loop(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(outbox_relay.asyncio, "sleep", stop_loop)

    with pytest.raises(asyncio.CancelledError):
        await outbox_relay.run()

    retention.assert_awaited_once()
    producer.stop.assert_awaited_once()


@pytest.mark.anyio
async def test_delete_retained_events_passes_seven_day_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from schedule_service.workers import outbox_relay

    outbox = AsyncMock()
    outbox.delete_published_before.return_value = 5

    class FakeUow:
        def __init__(self) -> None:
            self.outbox = outbox

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    session_factory = Mock()
    monkeypatch.setattr(outbox_relay, "SqlAlchemyUnitOfWork", lambda _: FakeUow())
    before = datetime.now(UTC)

    deleted = await outbox_relay._delete_retained_events(session_factory, 7)

    assert deleted == 5
    kwargs = outbox.delete_published_before.await_args.kwargs
    cutoff = kwargs["cutoff"]
    assert cutoff.tzinfo is not None
    assert (
        before - timedelta(days=7) - timedelta(seconds=5)
        <= cutoff
        <= datetime.now(UTC) - timedelta(days=7)
    )
