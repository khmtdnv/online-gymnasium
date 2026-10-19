from celery import Celery

from document_service.application.ports.document_task_outbox_repository import (
    PendingDocumentTask,
)


class CeleryTaskPublisher:
    """Отправляет имя задачи и ID задания в брокер через Celery."""

    def __init__(self, celery_app: Celery) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            celery_app: Приложение Celery с настроенным брокером.
        """
        self._celery_app = celery_app

    def publish(self, task: PendingDocumentTask) -> None:
        """Отправляет задачу Celery по имени с ID задания в аргументах.

        Здесь задача только отправляется; PDF строит отдельный воркер.

        Args:
            task: Задание outbox с именем задачи и ID документа.
        """
        self._celery_app.send_task(task.task_name, args=[str(task.document_job_id)])
