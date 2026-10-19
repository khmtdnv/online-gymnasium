from collections.abc import Callable
from typing import Self

from sqlalchemy.orm import Session

from document_service.infrastructure.document_repository import (
    SqlAlchemyDocumentRepository,
)
from document_service.infrastructure.document_task_outbox_repository import (
    SqlAlchemyDocumentTaskOutboxRepository,
)

type SessionFactory = Callable[[], Session]


class SqlAlchemyDocumentUnitOfWork:
    """Создаёт сессию, выполняет commit или rollback и закрывает её."""

    def __init__(self, session_factory: SessionFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            session_factory: Фабрика отдельной сессии для каждого Unit of Work.
        """
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        """Открывает сессию и предоставляет репозитории одной транзакции.

        Returns:
            Этот объект с репозиториями текущей сессии.
        """
        self._session = self._session_factory()
        self.documents = SqlAlchemyDocumentRepository(self._session)
        self.outbox = SqlAlchemyDocumentTaskOutboxRepository(self._session)
        return self

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
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()
