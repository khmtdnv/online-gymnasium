"""Чтение урока ученика только в его актуальном классе."""

from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from homework_service.application.homework import PositiveId
from homework_service.application.homework_results import _resolve_deadlines
from homework_service.application.ports.errors import (
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.application.ports.unit_of_work import UnitOfWork
from homework_service.application.teacher_lessons import TeacherLessonResult


class GetStudentLessonQuery(BaseModel):
    """Ученик из Gateway и ID урока без возможности выбрать чужой класс."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    lesson_id: PositiveId


class GetStudentLessonHandler:
    """Проверяет текущий класс до чтения двух групп ДЗ урока."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        schedule_reader: ScheduleReader,
        journal_reader: JournalReader,
    ) -> None:
        self._uow_factory = uow_factory
        self._schedule_reader = schedule_reader
        self._journal_reader = journal_reader

    async def handle(self, query: GetStudentLessonQuery) -> TeacherLessonResult:
        """Возвращает карточку своего класса; бывший/чужой урок выглядит как404."""
        class_id = await self._journal_reader.get_current_class_id(query.student_id)
        if class_id is None:
            raise HomeworkNotFoundError
        lesson = await self._schedule_reader.get_lesson(query.lesson_id)
        if lesson is None or lesson.class_id != class_id:
            raise HomeworkNotFoundError
        async with self._uow_factory() as uow:
            homeworks = await uow.homeworks.list_for_lesson(lesson.id)
            if any(
                row.class_id != class_id or row.subject_id != lesson.subject_id
                for row in homeworks
            ):
                raise OwnerLookupUnavailableError("Incompatible homework reference")
            files = (
                await uow.files.list_for_homeworks([row.id for row in homeworks])
                if homeworks
                else {}
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
