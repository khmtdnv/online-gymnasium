import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from aiokafka import AIOKafkaProducer

from schedule_service.application.outbox_relay import OutboxRelay
from schedule_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from schedule_service.infrastructure.kafka_event_publisher import KafkaEventPublisher
from schedule_service.infrastructure.unit_of_work import (
    AsyncSessionFactory,
    SqlAlchemyUnitOfWork,
)
from schedule_service.workers.config import RelaySettings

logger = logging.getLogger(__name__)


def _monotonic() -> float:
    """Returns the monotonic clock used to schedule retention runs."""
    return time.monotonic()


async def _delete_retained_events(
    session_factory: AsyncSessionFactory,
    retention_days: int,
) -> int:
    """Deletes published outbox events older than the retention window.

    Idempotency keys are never touched by the deletion.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        return await uow.outbox.delete_published_before(cutoff=cutoff)


async def run() -> None:
    """Публикует outbox в Kafka в цикле, повторяя работу после ошибки.

    При пустой пачке или ошибке делает паузу одну секунду. Раз в час удаляет
    опубликованные события старше окна удержания; сбой удержания не
    останавливает цикл публикации.
    """
    settings = RelaySettings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers, acks="all"
    )
    publisher = KafkaEventPublisher(
        producer,
        topic="schedule.lessons",
        snapshot_topic=settings.schedule_snapshot_topic,
    )
    relay = OutboxRelay(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        publisher=publisher,
        batch_size=settings.batch_size,
    )

    try:
        await producer.start()
        last_retention = _monotonic()

        while True:
            try:
                published = await relay.run_once()
            except Exception:
                logger.exception("Outbox relay failed to publish pending events")
                published = 0

            if _monotonic() - last_retention >= settings.retention_interval_seconds:
                last_retention = _monotonic()
                try:
                    deleted = await _delete_retained_events(
                        session_factory,
                        settings.published_retention_days,
                    )
                except Exception:
                    logger.exception("Outbox retention failed to delete events")
                else:
                    logger.info("Outbox retention deleted %d published events", deleted)

            await asyncio.sleep(0 if published else 1)
    finally:
        await producer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
