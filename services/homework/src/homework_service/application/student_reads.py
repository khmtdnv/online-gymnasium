"""Чтение ДЗ текущего класса с вычислением актуального срока."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from homework_service.application.homework import PositiveId
from homework_service.application.homework_results import (
    StudentHomeworkResult,
    _resolve_deadlines,
)
from homework_service.application.ports.errors import (
    HomeworkNotFoundError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.application.ports.unit_of_work import UnitOfWork


class ListStudentHomeworkQuery(BaseModel):
    """Доверенный ученик и границы страницы, не выбираемый клиентом класс."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    offset: int = Field(default=0, strict=True, ge=0, le=2147483647)


class GetStudentHomeworkQuery(BaseModel):
    """Доверенный ученик и ID запрошенного задания."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    homework_id: PositiveId


class ListStudentHomeworkHandler:
    """Читает только текущий класс и не использует дату прихода как фильтр."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal_reader: JournalReader,
        schedule_reader: ScheduleReader,
    ) -> None:
        """Сохраняет фабрику и авторитетные readers.

        Args:
            uow_factory: Отдельная транзакция чтения Homework.
            journal_reader: Текущий класс ученика.
            schedule_reader: Текущие уроки срока.
        """
        self._uow_factory = uow_factory
        self._journal_reader = journal_reader
        self._schedule_reader = schedule_reader

    async def handle(
        self, query: ListStudentHomeworkQuery
    ) -> list[StudentHomeworkResult]:
        """Проверяет класс перед выборкой и разрешает сроки после закрытия UoW.

        Args:
            query: Доверенный ученик и пагинация.

        Returns:
            Страница заданий с ожидаемыми и готовыми вложениями либо пустой список.

        Raises:
            OwnerLookupUnavailableError: Не удалось подтвердить класс или сроки.
        """
        class_id = await self._journal_reader.get_current_class_id(query.student_id)
        if class_id is None:
            return []
        async with self._uow_factory() as uow:
            homeworks = await uow.homeworks.list_for_class(
                class_id, query.limit, query.offset
            )
            files = {}
            if homeworks:
                files = await uow.files.list_for_homeworks(
                    [homework.id for homework in homeworks]
                )
        return await _resolve_deadlines(homeworks, self._schedule_reader, files)


class GetStudentHomeworkHandler:
    """Не допускает обход текущего класса прямой ссылкой на ID."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal_reader: JournalReader,
        schedule_reader: ScheduleReader,
    ) -> None:
        """Сохраняет зависимости без открытия запросов.

        Args:
            uow_factory: Новая транзакция Homework.
            journal_reader: Чтение актуального класса.
            schedule_reader: Чтение актуального срока.
        """
        self._uow_factory = uow_factory
        self._journal_reader = journal_reader
        self._schedule_reader = schedule_reader

    async def handle(self, query: GetStudentHomeworkQuery) -> StudentHomeworkResult:
        """Отличает доступное задание от отсутствующего или чужого.

        Args:
            query: Доверенный ученик и ID задания.

        Returns:
            Доступное задание с актуальным сроком и публичными метаданными файлов.

        Raises:
            HomeworkNotFoundError: Задание отсутствует или вне текущего класса.
            OwnerLookupUnavailableError: Не удалось подтвердить класс или срок.
        """
        class_id = await self._journal_reader.get_current_class_id(query.student_id)
        if class_id is None:
            raise HomeworkNotFoundError
        async with self._uow_factory() as uow:
            homework = await uow.homeworks.get_by_id(query.homework_id)
            if homework is None or homework.class_id != class_id:
                raise HomeworkNotFoundError
            files = await uow.files.list_for_homeworks([homework.id])
        return (await _resolve_deadlines([homework], self._schedule_reader, files))[0]
