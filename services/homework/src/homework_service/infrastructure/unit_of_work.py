"""Отдельная сессия и локальная транзакция для каждого сценария."""

from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from homework_service.infrastructure.homework_repository import (
    SqlAlchemyHomeworkRepository,
)


class SqlAlchemyUnitOfWork:
    """Завершает транзакцию и закрывает сессию даже при ошибке commit."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        """Сохраняет фабрику без открытия соединения.

        Args:
            session_factory: Фабрика новой сессии.
        """
        self._session_factory = session_factory

    async def __aenter__(self) -> Self:
        """Открывает сессию и предоставляет репозиторий текущей транзакции."""
        self._session = self._session_factory()
        self.homeworks = SqlAlchemyHomeworkRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Фиксирует успех, откатывает ошибку и всегда закрывает сессию.

        Args:
            exc_type: Тип исключения из тела транзакции.
            exc: Исключение из тела транзакции.
            tb: Его traceback.
        """
        try:
            if exc_type is not None:
                await self._session.rollback()
            else:
                try:
                    await self._session.commit()
                except BaseException:
                    await self._session.rollback()
                    raise
        finally:
            await self._session.close()
