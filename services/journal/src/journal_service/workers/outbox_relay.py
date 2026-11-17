"""Фоновая доставка сохранённых изменений состава в общую очередь."""

import asyncio
import json
import logging

from aiokafka import AIOKafkaProducer

from journal_service.application.outbox_relay import OutboxRelay
from journal_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from journal_service.workers.config import RelaySettings

logger = logging.getLogger(__name__)


async def run() -> None:
    """Повторяет отправку после сбоя, сохраняя event_id и не печатая payload."""
    settings = RelaySettings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers, acks="all"
    )

    async def publish(event: dict) -> None:
        await asyncio.wait_for(
            producer.send_and_wait(
                settings.platform_events_topic,
                json.dumps(event, separators=(",", ":")).encode(),
                key=event["payload"]["student_id"].encode(),
            ),
            timeout=15,
        )

    relay = OutboxRelay(
        lambda: SqlAlchemyUnitOfWork(sessions), publish, settings.batch_size
    )
    try:
        await producer.start()
        while True:
            try:
                count = await relay.run_once()
            except Exception:
                logger.exception(
                    "Journal outbox delivery failed; pending events retained"
                )
                count = 0
            await asyncio.sleep(0 if count else 1)
    finally:
        try:
            await producer.stop()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
