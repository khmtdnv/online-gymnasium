"""Запуск outbox → Kafka с повтором после ошибки и закрытием ресурсов."""

import asyncio
import json
import logging

from aiokafka import AIOKafkaProducer

from homework_service.application.outbox_relay import OutboxRelay
from homework_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from homework_service.workers.config import RelaySettings

logger = logging.getLogger(__name__)


async def run() -> None:
    """Работает отдельным процессом, не публикует данные до commit бизнес-сценария."""
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
                logger.exception("Outbox delivery failed; pending events retained")
                count = 0
            await asyncio.sleep(0 if count else 1)
    finally:
        try:
            await producer.stop()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
