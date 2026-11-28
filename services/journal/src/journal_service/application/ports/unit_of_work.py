from types import TracebackType
from typing import Protocol, Self

from journal_service.application.ports.class_repository import ClassRepository
from journal_service.application.ports.lesson_record_repository import (
    LessonRecordRepository,
)
from journal_service.application.ports.outbox_repository import OutboxRepository
from journal_service.application.ports.student_class_period_repository import (
    StudentClassPeriodRepository,
)
from journal_service.application.ports.teacher_class_repository import (
    TeacherClassRepository,
)


class UnitOfWork(Protocol):
    """Граница транзакции и доступа к репозиториям одного сценария."""

    classes: ClassRepository
    teacher_classes: TeacherClassRepository
    class_periods: StudentClassPeriodRepository
    lesson_records: LessonRecordRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> Self:
        """Открывает сессию и предоставляет репозитории одной транзакции.

        Returns:
            Этот объект с репозиториями текущей сессии.
        """
        ...

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
        ...
