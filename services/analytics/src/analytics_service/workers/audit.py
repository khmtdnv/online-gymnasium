"""Отдельная группа общего аудита, независимая от старого отчёта нагрузки."""

import asyncio
import base64
import json
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from analytics_service.application.audit import (
    parse_audit_event,
    parse_schedule_audit_event,
)
from analytics_service.config import AuditWorkerSettings
from analytics_service.infrastructure.clickhouse_audit_repository import (
    ClickHouseAuditRepository,
)
from analytics_service.infrastructure.clickhouse_connection import create_client

logger = logging.getLogger(__name__)


async def process_batch(
    fetched, repository, producer, consumer, *, dlq_topic: str, schedule_topic: str
) -> None:
    """Подтверждает offsets только после записи валидных строк и всех DLQ.

    Args:
        fetched: Пачки Kafka по partition.
        repository: Хранилище проверенных событий.
        producer: Отправитель карантинных сообщений.
        consumer: Получатель с отключённым auto-commit.
        dlq_topic: Отдельный топик ошибок общего аудита.
        schedule_topic: Топик существующего контракта snapshot v2.

    Raises:
        Exception: Запись/карантин не подтверждены; offsets не продвигаются.
    """
    events, malformed, offsets = [], [], {}
    for partition, messages in fetched.items():
        if not messages:
            continue
        offsets[partition] = messages[-1].offset + 1
        for message in messages:
            try:
                parse = (
                    parse_schedule_audit_event
                    if message.topic == schedule_topic
                    else parse_audit_event
                )
                events.append(parse(message.value))
            except ValueError, TypeError, UnicodeError:
                malformed.append(message)
    if events:
        await repository.add_many(events)
    for message in malformed:
        quarantine = {
            "source_topic": message.topic,
            "source_partition": message.partition,
            "source_offset": message.offset,
            "error_type": "InvalidAuditEvent",
            "original_value_base64": base64.b64encode(message.value).decode("ascii"),
        }
        await producer.send_and_wait(dlq_topic, json.dumps(quarantine).encode())
    if offsets:
        await consumer.commit(offsets)


async def run() -> None:
    """Запускает consumer и закрывает все ресурсы при ошибке или отмене процесса."""
    settings = AuditWorkerSettings()
    client = create_client(settings)
    consumer = AIOKafkaConsumer(
        settings.platform_events_topic,
        settings.schedule_snapshot_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.audit_group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        max_poll_interval_ms=300000,
    )
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers, acks="all"
    )
    try:
        await consumer.start()
        await producer.start()
        repository = ClickHouseAuditRepository(client)
        while True:
            fetched = await consumer.getmany(timeout_ms=1000, max_records=100)
            await process_batch(
                fetched,
                repository,
                producer,
                consumer,
                dlq_topic=settings.audit_dlq_topic,
                schedule_topic=settings.schedule_snapshot_topic,
            )
    except Exception:
        logger.error("Audit batch was not acknowledged; consumer will restart")
        raise
    finally:
        try:
            await consumer.stop()
        finally:
            try:
                await producer.stop()
            finally:
                await asyncio.to_thread(client.close)


if __name__ == "__main__":
    asyncio.run(run())
