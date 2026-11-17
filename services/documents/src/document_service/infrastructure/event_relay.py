"""Kafka-outbox документов; очередь задач Celery остаётся отдельной."""

import asyncio
import json
import logging
import signal
from datetime import UTC, datetime
from uuid import UUID

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from pydantic_settings import SettingsConfigDict
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from document_service.config import DocumentSettings
from document_service.infrastructure.database import create_engine, session_factory
from document_service.infrastructure.models.document_event_outbox import (
    DocumentEventRow,
)

logger = logging.getLogger(__name__)


class DocumentEventRelay:
    """Открывает короткие SQL-сессии до и после подтверждённой отправки."""

    def __init__(self, sessions, publish):
        self._sessions, self._publish = sessions, publish

    def _pending(self):
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(DocumentEventRow.envelope)
                    .where(DocumentEventRow.published_at.is_(None))
                    .order_by(DocumentEventRow.created_at, DocumentEventRow.event_id)
                    .limit(100)
                )
            )

    def _mark_published(self, event_id):
        with self._sessions() as session, session.begin():
            session.execute(
                update(DocumentEventRow)
                .where(
                    DocumentEventRow.event_id == event_id,
                    DocumentEventRow.published_at.is_(None),
                )
                .values(published_at=datetime.now(UTC))
            )

    async def run_once(self) -> int:
        """При сбое отправки оставляет текущее событие для безопасного повтора.

        Returns:
            Число событий, получивших подтверждение брокера и отметку в БД.
        """
        count = 0
        for event in await asyncio.to_thread(self._pending):
            await self._publish(event)
            await asyncio.to_thread(self._mark_published, UUID(event["event_id"]))
            count += 1
        return count


class EventWorkerSettings(DocumentSettings):
    """Транспорт общих событий вынесен в собственный worker-env."""

    model_config = SettingsConfigDict(env_file=(".env", ".worker.env"), extra="ignore")
    kafka_bootstrap_servers: str
    platform_events_topic: str = "platform.events.v1"


async def run():
    """Освобождает SQL/Kafka по остановке процесса, не скрывая недоставленные записи."""
    settings = EventWorkerSettings()
    engine = create_engine(settings.document_database_url)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers, acks="all"
    )
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, task.cancel)

    async def publish(event):
        await asyncio.wait_for(
            producer.send_and_wait(
                settings.platform_events_topic,
                json.dumps(event).encode(),
                key=event["payload"]["creator_id"].encode(),
            ),
            timeout=15,
        )

    relay = DocumentEventRelay(session_factory(engine), publish)
    try:
        await producer.start()
        while True:
            try:
                await relay.run_once()
            except (KafkaError, SQLAlchemyError, TimeoutError, OSError):
                logger.warning("Document event ACK missing; outbox retained")
            await asyncio.sleep(1)
    finally:
        await producer.stop()
        engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except asyncio.CancelledError:
        pass
