from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class PendingDocumentTask(BaseModel):
    """Непубликованное задание из outbox с именем задачи Celery."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: UUID
    document_job_id: UUID
    task_name: str
    created_at: AwareDatetime


class DocumentTaskOutboxRepository(Protocol):
    """Контракт чтения и отметки опубликованных задач outbox."""

    def get_pending(self, *, limit: int) -> list[PendingDocumentTask]:
        """Читает ограниченную пачку ещё не опубликованных записей outbox.

        Args:
            limit: Максимальное число записей в пачке.

        Returns:
            Непубликованные записи, не больше указанного limit.
        """
        ...

    def mark_published(self, *, task_id: UUID) -> None:
        """Ставит время публикации записи outbox в текущей транзакции.

        Args:
            task_id: ID записи задачи в outbox.
        """
        ...
