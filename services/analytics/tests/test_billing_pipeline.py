"""Изолированный Billing outbox → настоящий relay/Kafka → consumer/ClickHouse."""

import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from analytics_service.application.audit import AuditQuery
from analytics_service.infrastructure.clickhouse_audit_repository import (
    ClickHouseAuditRepository,
)
from analytics_service.workers.audit import process_batch
from analytics_service.workers.migrate_audit import prepare_audit_schema

PUBLISH = """
import asyncio, json, os
from datetime import date
from uuid import uuid4
from types import SimpleNamespace
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from billing_service.models import Base
from billing_service.storage import BillingStore
from billing_service.contracts import StartPayment, ProviderPayment
from billing_service.workers import relay

async def run():
    url = os.environ['BILLING_TEST_DATABASE_URL']
    assert make_url(url).database.startswith('billing_test_')
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = BillingStore(sessions)
    payment = await store.reserve_payment(StartPayment(student_id=uuid4(),payer_id=uuid4(),study_month=date(2026,10,1),request_key=uuid4()),300000)
    await store.apply_payment(payment.id, ProviderPayment.model_validate({
        'id': str(uuid4()),'status':'succeeded','paid':True,'test':True,
        'amount':{'value':'3000.00','currency':'RUB'},'recipient':{'account_id':'isolated-test'},
        'metadata':{'order_id':str(payment.order_id),'payment_id':str(payment.id)},
    }))
    event = next(row for row in await store.pending_events() if row['payload']['payment_id'] == payment.id)
    settings = SimpleNamespace(kafka_bootstrap_servers=os.environ['ANALYTICS_TEST_KAFKA_BOOTSTRAP_SERVERS'],platform_events_topic=os.environ['BILLING_TEST_TOPIC'])
    worker = asyncio.create_task(relay(settings,sessions))
    try:
        async with asyncio.timeout(30):
            while event['event_id'] in {row['event_id'] for row in await store.pending_events()}:
                if worker.done():
                    await worker
                await asyncio.sleep(0.1)
        print(json.dumps({'event_id':event['event_id']}))
    finally:
        worker.cancel()
        try: await worker
        except asyncio.CancelledError: pass
        await engine.dispose()
asyncio.run(run())
"""


def test_billing_relay_reaches_common_audit(legacy_clickhouse):
    broker = os.getenv("ANALYTICS_TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not broker or not os.getenv("BILLING_TEST_DATABASE_URL"):
        pytest.skip("Requires isolated Kafka and Billing PostgreSQL")
    topic = "billing-test-" + uuid4().hex
    result = subprocess.run(
        ["poetry", "-C", "services/billing", "run", "python", "-c", PUBLISH],
        cwd=Path(__file__).parents[3],
        env={**os.environ, "BILLING_TEST_TOPIC": topic},
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, "Isolated Billing relay failed"
    event_id = json.loads(result.stdout)["event_id"]
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
        today = datetime.now(UTC).date()
        try:
            await consumer.start()
            await producer.start()
            async with asyncio.timeout(30):
                while True:
                    batches = await consumer.getmany(timeout_ms=500, max_records=100)
                    await process_batch(
                        batches,
                        repository,
                        producer,
                        consumer,
                        dlq_topic=topic + "-dlq",
                        schedule_topic="unused",
                    )
                    rows = await repository.list_events(
                        AuditQuery(
                            date_from=today,
                            date_to=today,
                            event_source="billing",
                            limit=100,
                        )
                    )
                    found = [row for row in rows if str(row.event_id) == event_id]
                    if found:
                        assert len(found) == 1
                        assert found[0].payload["amount_kopecks"] == 300000
                        assert found[0].actor.id == "billing"
                        break
        finally:
            await consumer.stop()
            await producer.stop()

    asyncio.run(run())
