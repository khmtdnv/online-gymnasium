"""Общий формат чтения заданий и расчёт итоговых сроков."""

from dataclasses import asdict
from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from homework_service.application.homework import HomeworkResult
from homework_service.application.homework_files import HomeworkFileResult
from homework_service.application.ports.errors import OwnerLookupUnavailableError
from homework_service.application.ports.schedule_reader import (
    LessonInfo,
    ScheduleReader,
)
from homework_service.domain.homework import Homework
from homework_service.domain.homework_file import HomeworkFile


class StudentHomeworkResult(HomeworkResult):
    """Задание с вычисляемым сроком, не новой копией поля в БД."""

    final_due_datetime: AwareDatetime | None
    due_status: Literal["manual", "lesson", "lesson_cancelled"]

    @model_validator(mode="after")
    def validate_deadline(self) -> Self:
        """Проверяет связь режима срока с вычисленными полями."""
        if (self.due_lesson_id is None) == (self.manual_due_datetime is None):
            raise ValueError("Exactly one due mode is required")
        if self.manual_due_datetime is not None:
            valid = (
                self.due_status == "manual"
                and self.final_due_datetime == self.manual_due_datetime
            )
        else:
            valid = (
                self.due_status == "lesson"
                and self.final_due_datetime is not None
                or self.due_status == "lesson_cancelled"
                and self.final_due_datetime is None
            )
        if not valid:
            raise ValueError("Deadline state is inconsistent")
        return self


async def _resolve_deadlines(
    homeworks: list[Homework],
    schedule_reader: ScheduleReader,
    files: dict[int, list[HomeworkFile]] | None = None,
    *,
    due_lessons: dict[int, LessonInfo] | None = None,
) -> list[StudentHomeworkResult]:
    """Дополняет результаты одним пакетом Schedule без транзакции Homework.

    Args:
        homeworks: Уже разрешённые задания текущего класса.
        schedule_reader: Авторитетные уроки по сохранённым ссылкам.
        files: Вложения, заранее прочитанные одним пакетом по ID заданий.

    Returns:
        Задания в исходном порядке с актуальными сроками и публичными вложениями.

    Raises:
        OwnerLookupUnavailableError: Связанный урок исчез или несовместим с заданием.
    """
    ids = sorted(
        {row.due_lesson_id for row in homeworks if row.due_lesson_id is not None}
    )
    lessons = dict(due_lessons) if due_lessons is not None else {}
    if due_lessons is None:
        for offset in range(0, len(ids), 100):
            lessons.update(
                await schedule_reader.get_lessons(ids[offset : offset + 100])
            )
    results = []
    for homework in homeworks:
        final_due_datetime, status = homework.manual_due_datetime, "manual"
        if homework.due_lesson_id is not None:
            lesson = lessons.get(homework.due_lesson_id)
            if (
                lesson is None
                or lesson.id != homework.due_lesson_id
                or (
                    lesson.class_id != homework.class_id
                    or lesson.subject_id != homework.subject_id
                )
            ):
                raise OwnerLookupUnavailableError("Homework lesson is incompatible")
            final_due_datetime = (
                lesson.starts_at if lesson.status == "planned" else None
            )
            status = "lesson" if lesson.status == "planned" else "lesson_cancelled"
        results.append(
            StudentHomeworkResult(
                **asdict(homework),
                final_due_datetime=final_due_datetime,
                due_status=status,
                files=[
                    HomeworkFileResult.from_file(file)
                    for file in (files or {}).get(homework.id, [])
                ],
            )
        )
    return results
