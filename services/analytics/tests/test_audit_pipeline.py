"""Изолированная связка: проверка Homework/PG → relay/Kafka → consumer/ClickHouse."""

import asyncio
import os
import subprocess
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from analytics_service.application.audit import ProgressQuery
from analytics_service.infrastructure.clickhouse_audit_repository import (
    ClickHouseAuditRepository,
)
from analytics_service.workers.audit import process_batch
from analytics_service.workers.migrate_audit import prepare_audit_schema

PUBLISH = """
import asyncio, json, os
from uuid import uuid4
from sqlalchemy.engine import make_url
from aiokafka import AIOKafkaProducer
from homework_service.infrastructure.database import create_engine
from homework_service.application.homework_answers import ReviewHomeworkAnswerCommand, SubmitHomeworkAnswerCommand
from homework_service.application.outbox_relay import OutboxRelay
from homework_service.domain.homework import Homework
from tests.integration.test_homework_answers import handlers, STUDENT, TEACHER
from tests.test_domain_homework import data

async def run():
    url = os.environ['HOMEWORK_TEST_DATABASE_URL']
    if not (make_url(url).database or '').startswith('homework_test_'):
        raise RuntimeError('Disposable test DB required')
    engine = create_engine(url)
    producer = AIOKafkaProducer(bootstrap_servers=os.environ['ANALYTICS_TEST_KAFKA_BOOTSTRAP_SERVERS'], acks='all')
    try:
        uow, submit, review = handlers(engine)
        async with uow() as unit:
            # Старые события других тестов остаются в БД, но не входят в этот topic.
            old = {row['event_id'] for row in await unit.outbox.get_pending(limit=1000)}
            parent = await unit.homeworks.add(Homework(**data(author_id=TEACHER, issued_lesson_id=1000000 + uuid4().int % 1000000)))
        first = await submit.handle(SubmitHomeworkAnswerCommand(student_id=STUDENT,homework_id=parent.id,answer_text='Решение',idempotency_key='pipeline'))
        await review.handle(ReviewHomeworkAnswerCommand(teacher_id=TEACHER,homework_id=parent.id,answer_id=first.answer.id,status='graded',grade=5))
        await producer.start()
        async def publish(event):
            if event['event_id'] not in old:
                # Намеренно дублируем доставку для проверки отчёта до merge.
                for _ in range(2):
                    await producer.send_and_wait(os.environ['AUDIT_TEST_TOPIC'],json.dumps(event).encode())
        await OutboxRelay(uow,publish).run_once()
    finally:
        await producer.stop()
        await engine.dispose()
asyncio.run(run())
"""


def test_review_reaches_deduplicated_report_via_real_kafka(legacy_clickhouse):
    broker = os.getenv("ANALYTICS_TEST_KAFKA_BOOTSTRAP_SERVERS")
    source_db = os.getenv("HOMEWORK_TEST_DATABASE_URL")
    if not broker or not source_db:
        pytest.skip("Requires separate Kafka and disposable Homework PostgreSQL")
    topic = "audit-test-" + uuid4().hex
    root = Path(__file__).parents[3]
    result = subprocess.run(
        ["poetry", "-C", "services/homework", "run", "python", "-c", PUBLISH],
        cwd=root,
        env={**os.environ, "AUDIT_TEST_TOPIC": topic},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "Homework test publication failed"
    prepare_audit_schema(legacy_clickhouse)
    repository = ClickHouseAuditRepository(legacy_clickhouse)

    async def run():
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=broker,
            group_id=topic,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        producer = AIOKafkaProducer(bootstrap_servers=broker)
        try:
            await consumer.start()
            await producer.start()
            received = 0
            async with asyncio.timeout(30):
                while received < 2:
                    fetched = await consumer.getmany(timeout_ms=500, max_records=100)
                    await process_batch(
                        fetched,
                        repository,
                        producer,
                        consumer,
                        dlq_topic=topic + "-dlq",
                        schedule_topic="unused",
                    )
                    received += sum(len(rows) for rows in fetched.values())
            rows = await repository.get_progress(
                ProgressQuery(
                    class_id=7,
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 12, 31),
                )
            )
            assert (
                len(rows) == 1
                and rows[0].graded_count == 1
                and rows[0].average_grade == 5
            )
        finally:
            await consumer.stop()
            await producer.stop()

    asyncio.run(run())
