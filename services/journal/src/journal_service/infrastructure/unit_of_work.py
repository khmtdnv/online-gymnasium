from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.infrastructure.class_repository import SqlAlchemyClassRepository
from journal_service.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from journal_service.infrastructure.student_class_period_repository import (
    SqlAlchemyStudentClassPeriodRepository,
)
from journal_service.infrastructure.teacher_class_repository import (
    SqlAlchemyTeacherClassRepository,
)


class SqlAlchemyUnitOfWork:
    """Создаёт сессию, выполняет commit или rollback и закрывает её."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
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
        self.classes = SqlAlchemyClassRepository(self._session)
        self.teacher_classes = SqlAlchemyTeacherClassRepository(self._session)
        self.class_periods = SqlAlchemyStudentClassPeriodRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
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
