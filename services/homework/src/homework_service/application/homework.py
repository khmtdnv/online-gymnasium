"""Проверенные DTO и учебный сценарий создания домашнего задания."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from homework_service.application.homework_files import (
    HomeworkFileInput,
    HomeworkFileResult,
)
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    InvalidHomeworkDataError,
    LessonNotFoundError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.application.ports.unit_of_work import UnitOfWork
from homework_service.domain.homework import Homework

PositiveId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Description = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=10000
    ),
]


class CreateHomeworkCommand(BaseModel):
    """Описание, срок и ожидаемые файлы с доверенными учителем и уроком выдачи."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    teacher_id: UUID
    issued_lesson_id: PositiveId
    description: Description
    due_lesson_id: PositiveId | None = None
    manual_due_datetime: AwareDatetime | None = Field(default=None, strict=True)
    files: list[HomeworkFileInput] = Field(
        default_factory=list, max_length=5, strict=True
    )

    @model_validator(mode="after")
    def validate_due_mode(self) -> Self:
        """Оставляет ровно один способ срока без запроса к Schedule.

        Returns:
            Проверенная команда.

        Raises:
            ValueError: Указаны оба срока или ни одного.
        """
        if (self.due_lesson_id is None) == (self.manual_due_datetime is None):
            raise ValueError("Exactly one due mode is required")
        return self


class HomeworkResult(BaseModel):
    """Сохранённое задание с метаданными ожидаемых либо готовых вложений."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: PositiveId
    issued_lesson_id: PositiveId
    class_id: PositiveId
    subject_id: PositiveId
    author_id: UUID
    description: Description
    due_lesson_id: PositiveId | None
    manual_due_datetime: AwareDatetime | None
    created_at: AwareDatetime
    files: list[HomeworkFileResult] = Field(default_factory=list, max_length=5)

    @classmethod
    def from_homework(cls, homework: Homework) -> Self:
        """Преобразует сохранённый доменный объект в результат приложения.

        Args:
            homework: Задание с серверными ID и created_at.

        Returns:
            Проверенный результат среза создания.

        Raises:
            ValueError: Объект ещё не сохранён или его поля некорректны.
        """
        return cls.model_validate(asdict(homework))


class CreateHomeworkHandler:
    """Сохраняет ДЗ и ожидаемые вложения вместе после проверки урока и прав."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        schedule_reader: ScheduleReader,
        journal_reader: JournalReader,
        clock: Callable[[], datetime],
    ) -> None:
        """Сохраняет зависимости без запросов к БД и внешним сервисам.

        Args:
            uow_factory: Новая локальная транзакция для сохранения ДЗ.
            schedule_reader: Авторитетное чтение уроков.
            journal_reader: Проверка назначения учителя классу.
            clock: Функция текущего aware-времени; фиксируется в тестах.
        """
        self._uow_factory = uow_factory
        self._schedule_reader = schedule_reader
        self._journal_reader = journal_reader
        self._clock = clock

    async def handle(self, command: CreateHomeworkCommand) -> HomeworkResult:
        """Проверяет право преподавателя и срок перед локальным сохранением ДЗ.

        Args:
            command: Описание, один срок и доверенные ссылки учителя/урока.

        Returns:
            Задание и ожидаемые файлы после общей локальной транзакции.
            Байты файлов загружаются отдельно и не определяют видимость текста.

        Raises:
            LessonNotFoundError: Урок выдачи или выбранного срока отсутствует.
            HomeworkAccessDeniedError: Чужой/отменённый урок или нет назначения.
            InvalidHomeworkDataError: Выбранный срок недопустим.
            HomeworkAlreadyExistsError: Для урока уже создано задание.
            OwnerLookupUnavailableError: Владелец не позволил проверить данные.
        """
        issued_lesson = await self._schedule_reader.get_lesson(command.issued_lesson_id)

        if issued_lesson is None:
            raise LessonNotFoundError

        if (
            issued_lesson.teacher_id != command.teacher_id
            or issued_lesson.status == "canceled"
        ):
            raise HomeworkAccessDeniedError

        if not await self._journal_reader.is_teacher_assigned(
            command.teacher_id, issued_lesson.class_id
        ):
            raise HomeworkAccessDeniedError

        now = self._clock()

        if command.due_lesson_id:
            due_lesson = await self._schedule_reader.get_lesson(command.due_lesson_id)

            if due_lesson is None:
                raise LessonNotFoundError

            if (
                issued_lesson.class_id != due_lesson.class_id
                or due_lesson.status == "canceled"
                or issued_lesson.subject_id != due_lesson.subject_id
                or due_lesson.starts_at <= issued_lesson.starts_at
                or due_lesson.starts_at <= now
            ):
                raise InvalidHomeworkDataError

        else:
            if (
                command.manual_due_datetime <= issued_lesson.starts_at
                or command.manual_due_datetime <= now
            ):
                raise InvalidHomeworkDataError

        homework = Homework(
            issued_lesson_id=command.issued_lesson_id,
            class_id=issued_lesson.class_id,
            subject_id=issued_lesson.subject_id,
            author_id=command.teacher_id,
            description=command.description,
            due_lesson_id=command.due_lesson_id,
            manual_due_datetime=command.manual_due_datetime,
        )

        async with self._uow_factory() as uow:
            saved_homework = await uow.homeworks.add(homework)
            saved_files = (
                await uow.files.add_files(saved_homework.id, command.files)
                if command.files
                else []
            )

        return HomeworkResult(
            **asdict(saved_homework),
            files=[HomeworkFileResult.from_file(file) for file in saved_files],
        )
