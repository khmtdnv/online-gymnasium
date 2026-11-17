from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from celery import Celery
from celery.exceptions import Retry

from document_service.application.errors import TemporaryStorageError
from document_service.application.mark_job_failed import MarkJobFailedCommand
from document_service.infrastructure.celery_tasks import register_certificate_tasks


class TemporaryFailingHandler:
    def __init__(self, error: TemporaryStorageError) -> None:
        self._error = error

    def handle(self, job_id: UUID) -> None:
        raise self._error


class RecordingFailureHandler:
    def __init__(self) -> None:
        self.failed_jobs: list[tuple[UUID, str]] = []

    def handle(self, command: MarkJobFailedCommand) -> None:
        self.failed_jobs.append((command.job_id, command.error_message))


def make_task(
    core_handler: TemporaryFailingHandler,
    failure_handler: RecordingFailureHandler,
):
    celery_app = Celery(f"document-test-{uuid4()}")
    register_certificate_tasks(
        celery_app=celery_app,
        handler_factory=lambda: core_handler,
        failure_handler_factory=lambda: failure_handler,
    )
    return celery_app.tasks["documents.generate_certificate"]


def test_generation_task_uses_late_ack_and_requeues_lost_worker() -> None:
    """Брокер не должен считать PDF готовым до завершения обработчика."""
    task = make_task(
        TemporaryFailingHandler(TemporaryStorageError()), RecordingFailureHandler()
    )
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True


def test_task_retries_temporary_storage_error_after_one_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_error = TemporaryStorageError()
    task = make_task(
        core_handler=TemporaryFailingHandler(storage_error),
        failure_handler=RecordingFailureHandler(),
    )
    retry = Mock(side_effect=Retry())
    monkeypatch.setattr(task, "retry", retry)
    job_id = uuid4()
    task.push_request(retries=0)

    try:
        with pytest.raises(Retry):
            task.run(str(job_id))
    finally:
        task.pop_request()

    retry.assert_called_once_with(exc=storage_error, countdown=1)


def test_task_marks_job_failed_after_last_temporary_storage_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure_handler = RecordingFailureHandler()
    task = make_task(
        core_handler=TemporaryFailingHandler(TemporaryStorageError()),
        failure_handler=failure_handler,
    )
    retry = Mock(side_effect=AssertionError("retry must not be called"))
    monkeypatch.setattr(task, "retry", retry)
    job_id = uuid4()
    task.push_request(retries=3)

    try:
        task.run(str(job_id))
    finally:
        task.pop_request()

    assert failure_handler.failed_jobs == [(job_id, "Document generation failed")]
    retry.assert_not_called()


def test_certificate_tasks_use_handlers_from_their_own_app() -> None:
    """Одинаковое имя задачи не смешивает обработчики разных приложений."""
    first_failure_handler = RecordingFailureHandler()
    second_failure_handler = RecordingFailureHandler()
    with (
        Celery(f"document-first-{uuid4()}") as first_app,
        Celery(f"document-second-{uuid4()}") as second_app,
    ):
        register_certificate_tasks(
            first_app,
            handler_factory=lambda: TemporaryFailingHandler(TemporaryStorageError()),
            failure_handler_factory=lambda: first_failure_handler,
        )
        register_certificate_tasks(
            second_app,
            handler_factory=lambda: TemporaryFailingHandler(TemporaryStorageError()),
            failure_handler_factory=lambda: second_failure_handler,
        )
        first_job_id, second_job_id = uuid4(), uuid4()
        for app, job_id in (
            (first_app, first_job_id),
            (second_app, second_job_id),
        ):
            task = app.tasks["documents.generate_certificate"]
            task.push_request(retries=3)
            try:
                task.run(str(job_id))
            finally:
                task.pop_request()

    assert first_failure_handler.failed_jobs == [
        (first_job_id, "Document generation failed")
    ]
    assert second_failure_handler.failed_jobs == [
        (second_job_id, "Document generation failed")
    ]
