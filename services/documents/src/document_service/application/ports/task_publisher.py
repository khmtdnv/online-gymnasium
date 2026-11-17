from typing import Protocol

from document_service.application.ports.document_task_outbox_repository import (
    PendingDocumentTask,
)


class TaskPublisher(Protocol):
    """Контракт передачи задания из outbox исполнителю задач."""

    def publish(self, task: PendingDocumentTask) -> None:
        """Отправляет задачу Celery по имени с ID задания в аргументах.

        Здесь задача только отправляется; PDF строит отдельный воркер.

        Args:
            task: Задание outbox с именем задачи и ID документа.
        """
        ...
