from document_service.application.ports.task_publisher import TaskPublisher
from document_service.application.ports.unit_of_work import DocumentUnitOfWorkFactory


class DocumentTaskOutboxDispatcher:
    """Отправляет задачи из outbox в Celery и затем отмечает публикацию."""

    def __init__(
        self,
        uow_factory: DocumentUnitOfWorkFactory,
        publisher: TaskPublisher,
        batch_size: int = 100,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            publisher: Клиент отправки сообщений во внешний брокер.
            batch_size: Максимальное число записей для одной итерации отправки.
        """
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size

    def run_once(self) -> int:
        """Отправляет одну пачку задач Celery и отмечает публикацию каждой.

        Сбой после отправки до commit может привести к повторной отправке задачи.

        Returns:
            Количество отправленных задач.
        """
        with self._uow_factory() as uow:
            tasks = uow.outbox.get_pending(limit=self._batch_size)

        for task in tasks:
            self._publisher.publish(task)

            with self._uow_factory() as uow:
                uow.outbox.mark_published(task_id=task.id)

        return len(tasks)
