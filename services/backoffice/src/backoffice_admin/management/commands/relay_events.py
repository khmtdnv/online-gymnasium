"""Доставляет локальные результаты админ-действий в центральный аудит."""

import asyncio
import json
import logging
import os
from uuid import UUID

from aiokafka import AIOKafkaProducer
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connections
from django.utils import timezone

from backoffice_admin.models import AdminEventOutbox

logger = logging.getLogger(__name__)


def pending() -> list[dict]:
    """Читает100 ожидающих конвертов в DB-потоке Django без сетевого ожидания."""
    close_old_connections()
    return list(
        AdminEventOutbox.objects.filter(published_at__isnull=True)
        .order_by("created_at", "event_id")
        .values_list("envelope", flat=True)[:100]
    )


def mark_published(event_id: UUID) -> None:
    """Сохраняет подтверждение брокера, повторная отметка безопасна."""
    AdminEventOutbox.objects.filter(
        event_id=event_id, published_at__isnull=True
    ).update(published_at=timezone.now())


async def run() -> None:
    """Держит синхронный ORM вне event loop, закрывает Kafka и соединения БД."""
    producer = AIOKafkaProducer(
        bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"], acks="all"
    )
    topic = os.getenv("PLATFORM_EVENTS_TOPIC", "platform.events.v1")
    try:
        await producer.start()
        while True:
            try:
                events = await sync_to_async(pending, thread_sensitive=True)()
                for event in events:
                    await asyncio.wait_for(
                        producer.send_and_wait(
                            topic,
                            json.dumps(event).encode(),
                            key=event["actor"]["id"].encode(),
                        ),
                        timeout=15,
                    )
                    await sync_to_async(mark_published, thread_sensitive=True)(
                        UUID(event["event_id"])
                    )
                count = len(events)
            except Exception:
                logger.exception("Backoffice event delivery failed; events retained")
                count = 0
            await asyncio.sleep(0 if count else 1)
    finally:
        try:
            await producer.stop()
        finally:
            await sync_to_async(connections.close_all, thread_sensitive=True)()


class Command(BaseCommand):
    help = "Доставляет сохранённые события Backoffice в Kafka"

    def handle(self, *args, **options):
        """Запускает процесс; отмена не отмечает ожидающие события отправленными."""
        asyncio.run(run())
