"""Настоящий путь UUID: PostgreSQL → outbox → Kafka → worker → ClickHouse."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import TopicPartition

from analytics_service.config import AnalyticsSettings
from analytics_service.infrastructure.teacher_id_migration import prepare_uuid_schema
from analytics_service.workers import worker

PUBLISH = """
import asyncio, json, os
from datetime import UTC, datetime
from uuid import UUID
from alembic import command
from alembic.config import Config
from aiokafka import AIOKafkaProducer
from sqlalchemy.engine import make_url
from schedule_service.application.create_lesson import CreateLessonCommand, CreateLessonHandler
from schedule_service.application.outbox_relay import OutboxRelay
from schedule_service.infrastructure.database import create_engine, create_session_factory
from schedule_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from schedule_service.infrastructure.kafka_event_publisher import KafkaEventPublisher

url = os.environ['SCHEDULE_TEST_DATABASE_URL']
if not (make_url(url).database or '').startswith('schedule_test_'):
    raise RuntimeError('Only an explicit disposable database is allowed')
os.environ['DATABASE_URL'] = url
command.upgrade(Config('alembic.ini'), 'head')

async def main():
    engine = create_engine(url)
    factory = create_session_factory(engine)
    uow = lambda: SqlAlchemyUnitOfWork(factory)
    producer = AIOKafkaProducer(bootstrap_servers=os.environ['ANALYTICS_TEST_KAFKA_BOOTSTRAP_SERVERS'])
    try:
        lesson = await CreateLessonHandler(uow).handle(CreateLessonCommand(
            class_id=987654, teacher_id=UUID(os.environ['PIPELINE_TEACHER_ID']), subject_id=1,
            starts_at=datetime(2027,1,2,10,tzinfo=UTC), ends_at=datetime(2027,1,2,11,tzinfo=UTC)))
        await producer.start()
        publisher = KafkaEventPublisher(producer, os.environ['PIPELINE_TOPIC']+'.changed', os.environ['PIPELINE_TOPIC'])
        await OutboxRelay(uow, publisher).run_once()
        print(json.dumps({'lesson_id': lesson.id}))
    finally:
        await producer.stop()
        await engine.dispose()
asyncio.run(main())
"""


def test_uuid_snapshot_pipeline(legacy_clickhouse, monkeypatch):
    """Подтверждает offset только после реальной записи UUID-снимка в ClickHouse."""
    broker = os.environ.get("ANALYTICS_TEST_KAFKA_BOOTSTRAP_SERVERS")
    pg_url = os.environ.get("SCHEDULE_TEST_DATABASE_URL")
    if not broker or not pg_url:
        pytest.skip("Нужны отдельные тестовые PostgreSQL и Kafka")
    topic = "uuid-test-" + uuid4().hex
    group = topic + "-analytics"
    teacher = uuid4()
    prepare_uuid_schema(legacy_clickhouse)
    schedule = Path(__file__).resolve().parents[2] / "schedule"
    env = dict(os.environ, PIPELINE_TEACHER_ID=str(teacher), PIPELINE_TOPIC=topic)
    published = subprocess.run(
        ["poetry", "-C", str(schedule), "run", "python", "-c", PUBLISH],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    # Не выводим stderr: диагностические строки драйвера могут содержать URL.
    assert published.returncode == 0, "Schedule не завершил тестовую публикацию"
    lesson_id = json.loads(published.stdout.splitlines()[-1])["lesson_id"]
    settings = AnalyticsSettings(
        kafka_bootstrap_servers=broker,
        clickhouse_host="127.0.0.1",
        clickhouse_port=int(os.environ["ANALYTICS_TEST_CLICKHOUSE_PORT"]),
        clickhouse_user="default",
        clickhouse_password="",
        clickhouse_database=legacy_clickhouse.database,
        analytics_dlq_topic=topic + "-dlq",
        schedule_snapshot_topic=topic,
        schedule_snapshot_group_id=group,
    )
    monkeypatch.setattr(worker, "AnalyticsSettings", lambda: settings)

    async def consume():
        task = asyncio.create_task(worker.run())
        observer = AIOKafkaConsumer(bootstrap_servers=broker, group_id=group)
        try:
            await observer.start()
            async with asyncio.timeout(30):
                while await observer.committed(TopicPartition(topic, 0)) is None:
                    if task.done():
                        await task
                    await asyncio.sleep(0.1)
            rows = await asyncio.to_thread(
                legacy_clickhouse.query,
                "SELECT lesson_id,teacher_id FROM lesson_snapshots_v2",
            )
            assert rows.result_rows == [(lesson_id, teacher)]
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await observer.stop()

    asyncio.run(consume())
    legacy_clickhouse.command("SYSTEM REFRESH VIEW class_daily_workload_v2_mv")
    legacy_clickhouse.command("SYSTEM WAIT VIEW class_daily_workload_v2_mv")
    assert legacy_clickhouse.query(
        "SELECT class_id,planned_lessons_count,planned_minutes FROM class_daily_workload_v2"
    ).result_rows == [(987654, 1, 60)]
