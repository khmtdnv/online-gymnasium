"""Свой Kafka-consumer: подтверждение после PG либо безопасного DLQ, не до них."""

import asyncio
import hashlib
import json
import logging
import signal

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError
from pydantic_settings import SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from notifications_service.config import NotificationSettings
from notifications_service.contracts import EventConflictError, parse_event
from notifications_service.storage import NotificationStore

logger = logging.getLogger(__name__)


class WorkerSettings(NotificationSettings):
    """Отдельные env подключения к БД и транспорта доставки."""

    model_config = SettingsConfigDict(env_file=(".env", ".worker.env"), extra="ignore")
    kafka_bootstrap_servers: str
    platform_events_topic: str = "platform.events.v1"
    notifications_group_id: str = "notifications-v1"
    notifications_dlq_topic: str = "notifications.dlq"


async def process_batch(fetched, store, producer, consumer, *, dlq_topic: str):
    """Сбой SQL/ACK прерывает пакет; его offset нельзя подтвердить следующей порцией.

    Args:
        fetched: Пакет Kafka по разделам, без автоматического commit.
        store: Транзакционная запись inbox и личных уведомлений.
        producer: Отправка обезличенной ошибки в собственный DLQ.
        consumer: Ручное подтверждение всего успешно обработанного пакета.
        dlq_topic: Топик, не разделяемый с consumer аудита.
    """
    if not any(fetched.values()):
        return
    for records in fetched.values():
        for message in records:
            try:
                event = parse_event(message.value)
                if event is not None:
                    await store.record(event)
            except ValueError, EventConflictError:
                digest = hashlib.sha256(message.value).hexdigest()
                # Ни ошибочная фамилия, ни полный JSON не попадают в DLQ/логи.
                notice = {
                    "digest": digest,
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "reason": "invalid_notification_event",
                }
                await producer.send_and_wait(
                    dlq_topic, json.dumps(notice).encode(), key=digest.encode()
                )
    await consumer.commit()


async def run():
    """При ошибке завершает процесс, чтобы рестарт начал с последнего commit."""
    settings = WorkerSettings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    consumer = AIOKafkaConsumer(
        settings.platform_events_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.notifications_group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        acks="all",
        request_timeout_ms=15000,
    )
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, task.cancel)
    store = NotificationStore(async_sessionmaker(engine, expire_on_commit=False))
    try:
        await consumer.start()
        await producer.start()
        while True:
            fetched = await consumer.getmany(timeout_ms=1000, max_records=100)
            await process_batch(
                fetched,
                store,
                producer,
                consumer,
                dlq_topic=settings.notifications_dlq_topic,
            )
    finally:
        await consumer.stop()
        await producer.stop()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except asyncio.CancelledError:
        pass
    except SQLAlchemyError, KafkaError, OSError:
        logger.error(
            "Notification processing interrupted; restart will replay uncommitted offsets"
        )
        raise SystemExit(1) from None
