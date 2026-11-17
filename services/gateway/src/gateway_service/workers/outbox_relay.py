"""Доставка транзакционных событий Gateway с подтверждением брокера."""

import asyncio
import json
import logging
from uuid import UUID

from aiokafka import AIOKafkaProducer
from pydantic_settings import BaseSettings, SettingsConfigDict

from gateway_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from gateway_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)


class RelaySettings(BaseSettings):
    """Воркер не выпускает JWT и не требует их ключей для своей работы."""

    model_config = SettingsConfigDict(env_file=(".env", ".worker.env"), extra="ignore")
    database_url: str
    kafka_bootstrap_servers: str
    platform_events_topic: str = "platform.events.v1"


async def run() -> None:
    """Не держит SQL во время сети; после сбоя повторяет тот же event_id."""
    settings = RelaySettings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers, acks="all"
    )
    try:
        await producer.start()
        while True:
            try:
                async with SqlAlchemyUnitOfWork(sessions) as uow:
                    events = await uow.outbox.get_pending(limit=100)
                for event in events:
                    await asyncio.wait_for(
                        producer.send_and_wait(
                            settings.platform_events_topic,
                            json.dumps(event).encode(),
                            key=event["payload"]["user_id"].encode(),
                        ),
                        timeout=15,
                    )
                    async with SqlAlchemyUnitOfWork(sessions) as uow:
                        await uow.outbox.mark_published(UUID(event["event_id"]))
                count = len(events)
            except Exception:
                logger.exception("Gateway outbox delivery failed; events retained")
                count = 0
            await asyncio.sleep(0 if count else 1)
    finally:
        try:
            await producer.stop()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
