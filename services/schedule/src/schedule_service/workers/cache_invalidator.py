import asyncio
import json
import logging
from datetime import date

import redis.asyncio as redis
from aiokafka import AIOKafkaConsumer

from schedule_service.application.cache_invalidator import CacheInvalidator
from schedule_service.domain.events import ScheduleChanged
from schedule_service.infrastructure.redis_schedule_cache import RedisScheduleCache
from schedule_service.workers.config import InvalidatorSettings

logger = logging.getLogger(__name__)


async def run() -> None:
    """Читает события Kafka пачками и удаляет кеш изменённых дней.

    Забирает до 100 сообщений одним getmany, инвалидирует кеш всех событий
    пачки и подтверждает смещения после обработки пачки. При ошибке
    прекращает работу и закрывает клиентов; пачка может быть доставлена
    повторно.
    """
    settings = InvalidatorSettings()
    consumer = AIOKafkaConsumer(
        "schedule.lessons",
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="schedule-cache-invalidator",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    cache = RedisScheduleCache(redis_client)
    invalidator = CacheInvalidator(cache)

    try:
        await consumer.start()

        while True:
            try:
                fetched = await consumer.getmany(timeout_ms=1000, max_records=100)

                events: list[ScheduleChanged] = []
                offsets_to_commit = {}

                for topic_partition, messages in fetched.items():
                    if not messages:
                        continue

                    offsets_to_commit[topic_partition] = messages[-1].offset + 1

                    for message in messages:
                        envelope = json.loads(message.value)
                        if envelope["event_type"] == "schedule.changed":
                            payload = envelope["payload"]
                            events.append(
                                ScheduleChanged(
                                    lesson_id=payload["lesson_id"],
                                    class_id=payload["class_id"],
                                    affected_dates=tuple(
                                        date.fromisoformat(day)
                                        for day in payload["affected_dates"]
                                    ),
                                )
                            )

                for event in events:
                    await invalidator.handle(event)

                for topic_partition, next_offset in offsets_to_commit.items():
                    await consumer.commit({topic_partition: next_offset})

            except Exception:
                logger.exception("Cache invalidator failed to process Kafka batch")
                raise
    finally:
        try:
            await consumer.stop()
        finally:
            await cache.aclose()


if __name__ == "__main__":
    asyncio.run(run())
