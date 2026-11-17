"""Свежие права на файлы существующего задания, без проверки срока новой выдачи."""

from uuid import UUID

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    OwnerLookupUnavailableError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.domain.homework import Homework


async def check_teacher_access(
    teacher_id: UUID,
    homework: Homework,
    schedule_reader: ScheduleReader,
    journal_reader: JournalReader,
) -> None:
    """Проверяет текущего преподавателя урока выдачи и назначение классу.

    Args:
        teacher_id: UUID пользователя из доверенного контекста Gateway.
        homework: Уже найденное локальное задание.
        schedule_reader: Авторитетный владелец уроков.
        journal_reader: Авторитетный владелец назначений преподавателей.

    Raises:
        HomeworkAccessDeniedError: Урок удалён, чужой либо назначение снято.
        OwnerLookupUnavailableError: Нет ответа владельца или ссылки несовместимы.
    """
    lesson = await schedule_reader.get_lesson(homework.issued_lesson_id)
    if lesson is None or lesson.teacher_id != teacher_id:
        raise HomeworkAccessDeniedError
    if (
        lesson.id != homework.issued_lesson_id
        or lesson.class_id != homework.class_id
        or lesson.subject_id != homework.subject_id
    ):
        raise OwnerLookupUnavailableError("Incompatible homework lesson")
    if not await journal_reader.is_teacher_assigned(teacher_id, homework.class_id):
        raise HomeworkAccessDeniedError
