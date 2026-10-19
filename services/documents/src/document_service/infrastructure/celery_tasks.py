from collections.abc import Callable
from uuid import UUID

from celery import Celery

from document_service.application.errors import (
    PermanentDocumentError,
    TemporaryStorageError,
)
from document_service.application.generate_certificate import (
    GenerateCertificateCommand,
    GenerateCertificateHandler,
)
from document_service.application.mark_job_failed import (
    MarkJobFailedCommand,
    MarkJobFailedHandler,
)


def register_certificate_tasks(
    celery_app: Celery,
    handler_factory: Callable[[], GenerateCertificateHandler],
    failure_handler_factory: Callable[[], MarkJobFailedHandler],
) -> None:
    """Регистрирует задачу генерации справки только в переданном приложении.

    Фабрики обработчиков принадлежат этому приложению и не передаются другим
    приложениям Celery через общую регистрацию задач.

    Args:
        celery_app: Приложение Celery с настроенным брокером.
        handler_factory: Фабрика обработчика генерации справки.
        failure_handler_factory: Фабрика обработчика окончательной ошибки задания.
    """

    @celery_app.task(
        name="documents.generate_certificate",
        ignore_result=True,
        bind=True,
        shared=False,
    )
    def generate_certificate(self, job_id: str) -> None:
        """Запускает генерацию справки и повторяет временную ошибку хранилища.

        После трёх повторов записывает failed. Постоянная ошибка завершает задачу без
        retry.

        Args:
            job_id: ID задания генерации документа.

        Raises:
            celery.exceptions.Retry: Временная ошибка запланировала повтор задачи.
        """
        try:
            handler = handler_factory()
            handler.handle(GenerateCertificateCommand(job_id=UUID(job_id)))

        except TemporaryStorageError as exc:
            if self.request.retries >= 3:
                failure_handler = failure_handler_factory()

                failure_handler.handle(
                    command=MarkJobFailedCommand(
                        job_id=UUID(job_id),
                        error_message="Document generation failed",
                    )
                )
                return

            raise self.retry(exc=exc, countdown=2**self.request.retries)

        except PermanentDocumentError:
            return
