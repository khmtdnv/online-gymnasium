"""ACK Kafka подтверждает именно опубликованное событие готовности документа."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def test_document_event_remains_pending_until_publish_ack():
    from document_service.application.templates import CreateTemplateCommand
    from document_service.infrastructure.database import create_engine
    from document_service.infrastructure.document_repository import (
        SqlAlchemyDocumentRepository,
    )
    from document_service.infrastructure.event_relay import DocumentEventRelay
    from document_service.infrastructure.models.base import Base
    from document_service.infrastructure.models.document_event_outbox import (
        DocumentEventRow,
    )

    url = os.getenv("DOCUMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires isolated PostgreSQL")
    assert make_url(url).database.startswith("document_test_")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    try:
        with sessions() as session, session.begin():
            repo = SqlAlchemyDocumentRepository(session)
            job = repo.create_template_job(
                CreateTemplateCommand(
                    creator_id=uuid4(),
                    request_key=uuid4(),
                    document_type="certificate",
                    payload={
                        "student_full_name": "Иван Петров",
                        "class_name": "7А",
                        "academic_year": "2026/2027",
                    },
                )
            )
            repo.mark_completed(job.id, "test.pdf")
        received = []

        async def unavailable(event):
            raise OSError("ACK lost")

        async def publish(event):
            received.append(event)

        async def run():
            with pytest.raises(OSError):
                await DocumentEventRelay(sessions, unavailable).run_once()
            assert await DocumentEventRelay(sessions, publish).run_once() >= 1

        asyncio.run(run())
        own = next(
            event for event in received if event["payload"]["job_id"] == str(job.id)
        )
        with sessions() as session:
            assert (
                session.get(DocumentEventRow, own["event_id"]).published_at is not None
            )
    finally:
        engine.dispose()
