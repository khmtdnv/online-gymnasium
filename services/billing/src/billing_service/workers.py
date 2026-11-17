"""Раздельные процессы сверки ЮKassa и доставки outbox; сбой Kafka не тормозит сверку."""

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from pydantic_settings import SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from billing_service.config import BillingSettings
from billing_service.invoice_worker import issue_quarter_invoices
from billing_service.provider import ProviderUnavailableError, RefundNotAllowedError
from billing_service.runtime import create_service
from billing_service.storage import BillingConflictError, BillingStore

logger = logging.getLogger(__name__)


class WorkerSettings(BillingSettings):
    """API и worker разделяют данные БД, транспорт вынесен в.worker.env."""

    model_config = SettingsConfigDict(env_file=(".env", ".worker.env"), extra="ignore")
    kafka_bootstrap_servers: str = ""
    platform_events_topic: str = "platform.events.v1"
    journal_base_url: str = ""
    journal_service_token: str = ""


async def reconcile(settings, sessions):
    """Проверяет по20 старейших попыток; ни один сбой не считается отменой."""
    async with httpx.AsyncClient(follow_redirects=False) as http:
        service = create_service(settings, http, sessions)
        while True:
            if service.provider is not None:
                for payment_id in await service.store.pending_ids():
                    try:
                        await service.refresh_payment(payment_id)
                    except ProviderUnavailableError, BillingConflictError:
                        logger.warning("Payment remains unresolved id=%s", payment_id)
                for refund_id in await service.store.pending_ids(refund=True):
                    try:
                        await service.refresh_refund(refund_id)
                    except (
                        ProviderUnavailableError,
                        RefundNotAllowedError,
                        BillingConflictError,
                    ):
                        logger.warning("Refund remains unresolved id=%s", refund_id)
            await asyncio.sleep(30)


async def relay(settings, sessions):
    """Подтверждает локальный published_at только после Kafka ack."""
    if not settings.kafka_bootstrap_servers:
        raise RuntimeError("Kafka configuration missing")
    store = BillingStore(sessions)
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers, acks="all"
    )
    try:
        await producer.start()
        while True:
            events = await store.pending_events()
            try:
                for event in events:
                    await asyncio.wait_for(
                        producer.send_and_wait(
                            settings.platform_events_topic,
                            json.dumps(event).encode(),
                            key=event["payload"]["student_id"].encode(),
                        ),
                        timeout=15,
                    )
                    await store.mark_published(UUID(event["event_id"]))
            except KafkaError, SQLAlchemyError, TimeoutError, OSError:
                # Не логируем request/credentials/сырые данные провайдера.
                logger.warning(
                    "Billing audit delivery not acknowledged; events retained"
                )
            await asyncio.sleep(1)
    finally:
        await producer.stop()


async def invoices(settings, sessions):
    """Периодически повторяет начисления, не создавая платежей или дубликатов."""
    if not settings.journal_base_url or not settings.journal_service_token:
        raise RuntimeError("Journal invoice reader configuration missing")
    store = BillingStore(sessions)
    async with httpx.AsyncClient(base_url=settings.journal_base_url) as http:
        while True:
            try:
                await issue_quarter_invoices(
                    http,
                    settings.journal_service_token,
                    store,
                    datetime.now(ZoneInfo("Europe/Moscow")).date(),
                    settings.quarter_price_kopecks,
                )
            except httpx.HTTPError, SQLAlchemyError, ValueError, OSError:
                logger.exception("Quarter invoice cycle failed; will retry")
            await asyncio.sleep(3600)


async def run(kind: str):
    """Отменяет asyncio-задачу поSIGTERM, освобождая свои HTTP/SQL/Kafka ресурсы."""
    settings = WorkerSettings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, task.cancel)
    try:
        worker = {"reconcile": reconcile, "relay": relay, "invoices": invoices}[kind]
        await worker(settings, async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"reconcile", "relay", "invoices"}:
        raise SystemExit("Expected reconcile, relay or invoices")
    try:
        asyncio.run(run(sys.argv[1]))
    except asyncio.CancelledError:
        pass
