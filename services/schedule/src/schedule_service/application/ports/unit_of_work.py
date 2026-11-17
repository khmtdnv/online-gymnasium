from collections.abc import Callable
from typing import Protocol, Self

from schedule_service.application.ports.idempotency_repository import (
    IdempotencyRepository,
)
from schedule_service.application.ports.lesson_repository import LessonRepository
from schedule_service.application.ports.outbox_repository import OutboxRepository
from schedule_service.application.ports.subject_repository import SubjectRepository


class UnitOfWork(Protocol):
    """Граница транзакции и доступа к репозиториям одного сценария."""

    lessons: LessonRepository
    idempotency: IdempotencyRepository
    outbox: OutboxRepository
    subjects: SubjectRepository

    async def __aenter__(self) -> Self:
        """Открывает сессию и предоставляет репозитории одной транзакции.

        Returns:
            Этот объект с репозиториями текущей сессии.
        """
        ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Завершает транзакцию и закрывает сессию.

        При успешном выходе выполняет commit, при исключении выполняет rollback.

        Args:
            exc_type: Тип исключения при выходе; None при успешном завершении.
            exc: Исключение, которое нужно обработать, если оно возникло.
            tb: Объект traceback исключения, если оно возникло.
        """
        ...


type UnitOfWorkFactory = Callable[[], UnitOfWork]
