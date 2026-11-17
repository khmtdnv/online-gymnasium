"""Карточка своего урока с заданиями к нему и из него."""

from collections.abc import Callable
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from homework_service.application.homework import PositiveId
from homework_service.application.homework_results import (
    StudentHomeworkResult,
    _resolve_deadlines,
)
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import (
    LessonInfo,
    ScheduleReader,
)
from homework_service.application.ports.unit_of_work import UnitOfWork


class GetTeacherLessonQuery(BaseModel):
    """Урок и UUID преподавателя, полученный от доверенного Gateway."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    teacher_id: UUID
    lesson_id: PositiveId


class TeacherLessonResult(BaseModel):
    """Открытый урок, следующий кандидат и две непересекающиеся группы ДЗ."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson: LessonInfo
    next_lesson: LessonInfo | None
    homework_for_lesson: list[StudentHomeworkResult]
    homework_from_lesson: list[StudentHomeworkResult]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Проверяет связи карточки без дополнительных сетевых запросов."""
        if self.next_lesson is not None and (
            self.lesson.status == "canceled"
            or self.next_lesson.class_id != self.lesson.class_id
            or self.next_lesson.subject_id != self.lesson.subject_id
            or self.next_lesson.starts_at <= self.lesson.starts_at
            or self.next_lesson.status != "planned"
        ):
            raise ValueError("Invalid next lesson")
        if len(self.homework_from_lesson) > 1:
            raise ValueError("Multiple assignments from one lesson")
        homeworks = self.homework_for_lesson + self.homework_from_lesson
        if len({row.id for row in homeworks}) != len(homeworks):
            raise ValueError("Duplicate homework")
        for group, from_lesson in (
            (self.homework_for_lesson, False),
            (self.homework_from_lesson, True),
        ):
            keys = [(row.created_at, row.id) for row in group]
            if keys != sorted(keys, reverse=True):
                raise ValueError("Invalid homework order")
            for row in group:
                if (
                    row.class_id != self.lesson.class_id
                    or row.subject_id != self.lesson.subject_id
                    or (row.issued_lesson_id if from_lesson else row.due_lesson_id)
                    != self.lesson.id
                ):
                    raise ValueError("Incompatible homework reference")
                if not from_lesson and (
                    row.due_status
                    != (
                        "lesson"
                        if self.lesson.status == "planned"
                        else "lesson_cancelled"
                    )
                    or row.final_due_datetime
                    != (
                        self.lesson.starts_at
                        if self.lesson.status == "planned"
                        else None
                    )
                ):
                    raise ValueError("Homework deadline differs from included lesson")
        return self


class GetTeacherLessonHandler:
    """Проверяет собственный урок и актуальное назначение до чтения заданий."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        schedule_reader: ScheduleReader,
        journal_reader: JournalReader,
    ) -> None:
        """Сохраняет зависимости без открытия сессии.

        Args:
            uow_factory: Фабрика локальной транзакции Homework.
            schedule_reader: Владелец сведений об уроках.
            journal_reader: Владелец актуальных назначений преподавателей.
        """
        self._uow_factory = uow_factory
        self._schedule_reader = schedule_reader
        self._journal_reader = journal_reader

    async def handle(self, query: GetTeacherLessonQuery) -> TeacherLessonResult:
        """Собирает разрешённую карточку после проверки владельцев.

        Args:
            query: Доверенный преподаватель и запрошенный урок.

        Returns:
            Урок и обе группы заданий со сроками и метаданными вложений.

        Raises:
            LessonNotFoundError: Урок не существует.
            HomeworkAccessDeniedError: Урок чужой или назначение снято.
            OwnerLookupUnavailableError: Владелец недоступен или связи испорчены.
        """
        lesson = await self._schedule_reader.get_lesson(query.lesson_id)
        if lesson is None:
            raise LessonNotFoundError
        if lesson.teacher_id != query.teacher_id:
            raise HomeworkAccessDeniedError
        if not await self._journal_reader.is_teacher_assigned(
            query.teacher_id, lesson.class_id
        ):
            raise HomeworkAccessDeniedError
        async with self._uow_factory() as uow:
            homeworks = await uow.homeworks.list_for_lesson(query.lesson_id)
            if any(
                row.class_id != lesson.class_id or row.subject_id != lesson.subject_id
                for row in homeworks
            ):
                raise OwnerLookupUnavailableError("Incompatible homework reference")
            files = {}
            if homeworks:
                files = await uow.files.list_for_homeworks(
                    [homework.id for homework in homeworks]
                )
        results = await _resolve_deadlines(homeworks, self._schedule_reader, files)
        next_lesson = (
            await self._schedule_reader.get_next_lesson(lesson.id)
            if lesson.status == "planned"
            else None
        )
        try:
            return TeacherLessonResult(
                lesson=lesson,
                next_lesson=next_lesson,
                homework_for_lesson=[
                    row for row in results if row.due_lesson_id == lesson.id
                ],
                homework_from_lesson=[
                    row for row in results if row.issued_lesson_id == lesson.id
                ],
            )
        except ValueError as exc:
            raise OwnerLookupUnavailableError("Incompatible lesson card") from exc
