from collections.abc import Callable
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from schedule_service.infrastructure.idempotency_repository import (
    SqlAlchemyIdempotencyRepository,
)
from schedule_service.infrastructure.lesson_repository import SqlAlchemyLessonRepository
from schedule_service.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from schedule_service.infrastructure.subject_repository import (
    SqlAlchemySubjectRepository,
)

type AsyncSessionFactory = Callable[[], AsyncSession]


class SqlAlchemyUnitOfWork:
    """Создаёт сессию, выполняет commit или rollback и закрывает её."""

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            session_factory: Фабрика отдельной сессии для каждого Unit of Work.
        """
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        """Открывает сессию и предоставляет репозитории одной транзакции.

        Returns:
            Этот объект с репозиториями текущей сессии.
        """
        self._session = self._session_factory()
        self.lessons = SqlAlchemyLessonRepository(self._session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        self.subjects = SqlAlchemySubjectRepository(self._session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Завершает транзакцию и закрывает сессию.

        При успешном выходе выполняет commit, при исключении выполняет rollback.

        Args:
            exc_type: Тип исключения при выходе; None при успешном завершении.
            exc: Исключение, которое нужно обработать, если оно возникло.
            tb: Объект traceback исключения, если оно возникло.
        """
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
