"""Собственная PostgreSQL: один ключ, одно задание, одно завершение и событие."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def test_template_job_retry_ownership_and_terminal_event_are_transactional():
    from document_service.application.templates import (
        CreateTemplateCommand,
        TemplateConflictError,
    )
    from document_service.infrastructure.database import create_engine
    from document_service.infrastructure.document_repository import (
        SqlAlchemyDocumentRepository,
    )
    from document_service.infrastructure.models.base import Base
    from document_service.infrastructure.models.document_event_outbox import (
        DocumentEventRow,
    )
    from document_service.infrastructure.models.document_task_outbox import (
        DocumentTaskOutboxRow,
    )

    url = os.getenv("DOCUMENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires isolated PostgreSQL")
    assert make_url(url).database.startswith("document_test_")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    creator = uuid4()
    command = CreateTemplateCommand(
        creator_id=creator,
        request_key=uuid4(),
        document_type="contract",
        payload={
            "student_full_name": "Петров Иван",
            "class_name": "7А",
            "academic_year": "2026/2027",
        },
    )

    def create():
        with sessions() as session, session.begin():
            return SqlAlchemyDocumentRepository(session).create_template_job(command)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: create(), range(2)))
        assert first.id == second.id
        with sessions() as session, session.begin():
            repo = SqlAlchemyDocumentRepository(session)
            assert len(repo.list_jobs(creator, 50, 0)) == 1
            assert repo.list_jobs(uuid4(), 50, 0) == []
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentTaskOutboxRow)
                    .where(DocumentTaskOutboxRow.document_job_id == first.id)
                )
                == 1
            )
            with pytest.raises(TemplateConflictError):
                repo.create_template_job(
                    command.model_copy(update={"document_type": "certificate"})
                )
            repo.mark_processing(first.id)
            repo.mark_completed(first.id, f"documents/{first.id}.pdf")
        with sessions() as session, session.begin():
            repo = SqlAlchemyDocumentRepository(session)
            repo.mark_processing(first.id)
            repo.mark_failed(first.id, "late failure")
            repo.mark_completed(first.id, f"documents/{first.id}.pdf")
        with sessions() as session:
            repo = SqlAlchemyDocumentRepository(session)
            assert repo.get_job(first.id).status.value == "completed"
            events = list(
                session.scalars(
                    select(DocumentEventRow).where(
                        DocumentEventRow.envelope["payload"]["job_id"].astext
                        == str(first.id)
                    )
                )
            )
            assert len(events) == 1
            assert events[0].envelope["payload"]["creator_id"] == str(creator)
            assert "student_full_name" not in events[0].envelope["payload"]
    finally:
        engine.dispose()
