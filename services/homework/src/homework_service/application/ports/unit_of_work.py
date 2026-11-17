"""Одна локальная транзакция Homework."""

from types import TracebackType
from typing import Protocol, Self

from homework_service.application.ports.homework_answer_file_repository import (
    HomeworkAnswerFileRepository,
)
from homework_service.application.ports.homework_answer_repository import (
    HomeworkAnswerRepository,
)
from homework_service.application.ports.homework_file_repository import (
    HomeworkFileRepository,
)
from homework_service.application.ports.homework_repository import HomeworkRepository
from homework_service.application.ports.outbox_repository import OutboxRepository


class UnitOfWork(Protocol):
    """Объединяет репозиторий и завершение транзакции."""

    homeworks: HomeworkRepository
    files: HomeworkFileRepository
    answers: HomeworkAnswerRepository
    answer_files: HomeworkAnswerFileRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> Self:
        """Открывает отдельную сессию и возвращает текущий UoW."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Фиксирует успех или откатывает ошибку, затем закрывает сессию.

        Args:
            exc_type: Тип ошибки, если тело транзакции завершилось исключением.
            exc: Исключение тела транзакции.
            tb: Его traceback.
        """
        ...
