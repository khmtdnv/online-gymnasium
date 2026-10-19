from collections.abc import Callable
from typing import Protocol, Self

from document_service.application.ports.document_repository import DocumentRepository
from document_service.application.ports.document_task_outbox_repository import (
    DocumentTaskOutboxRepository,
)


class DocumentUnitOfWork(Protocol):
    """Граница транзакции и доступа к репозиториям одного сценария."""

    documents: DocumentRepository
    outbox: DocumentTaskOutboxRepository

    def __enter__(self) -> Self:
        """Открывает сессию и предоставляет репозитории одной транзакции.

        Returns:
            Этот объект с репозиториями текущей сессии.
        """
        ...

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        """Завершает транзакцию и закрывает сессию.

        При успешном выходе выполняет commit, при исключении выполняет rollback.

        Args:
            exc_type: Тип исключения при выходе; None при успешном завершении.
            exc: Исключение, которое нужно обработать, если оно возникло.
            traceback: Объект traceback исключения, если оно возникло.
        """
        ...


type DocumentUnitOfWorkFactory = Callable[[], DocumentUnitOfWork]
