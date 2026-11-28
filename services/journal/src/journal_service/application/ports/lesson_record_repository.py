"""Контракт чтения и изменения записей урока."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from journal_service.domain.lesson_records import LessonAttendance, LessonGrade


@dataclass(frozen=True)
class SubjectAverage:
    """Средняя оценка по предмету за период и число учтённых оценок."""

    subject_id: int
    average: Decimal
    grade_count: int


class LessonRecordRepository(Protocol):
    """Предоставляет записи урока и агрегаты дневника."""

    async def replace_lesson_entries(
        self,
        lesson_id: int,
        attendance: list[LessonAttendance],
        grades: list[LessonGrade],
    ) -> tuple[list[LessonAttendance], list[LessonGrade]]:
        """Заменяет записи урока содержимым пакета одной транзакцией.

        Вставляет и обновляет строки пакета (автор строк — автор команды,
        генераторные строки становятся живыми), удаляет строки урока,
        отсутствующие в пакете, и оценки учеников, чья посещаемость в
        пакете не `present`.

        Args:
            lesson_id: Урок, записи которого заменяются.
            attendance: Посещаемость пакета на этом уроке.
            grades: Оценки пакета на этом уроке.

        Returns:
            Полное состояние записей урока после замены.
        """
        ...

    async def list_lesson_entries(
        self, lesson_id: int
    ) -> tuple[list[LessonAttendance], list[LessonGrade]]:
        """Читает все записи одного урока для формы правки.

        Args:
            lesson_id: Урок, записи которого читаются.

        Returns:
            Посещаемость и оценки урока; пустые списки, если записей нет.
        """
        ...

    async def list_student_entries(
        self, student_id: UUID, date_from: date, date_to: date
    ) -> tuple[list[LessonAttendance], list[LessonGrade]]:
        """Читает записи ученика окном дат включительно.

        Args:
            student_id: Ученик, чьи записи читаются.
            date_from: Начальная дата окна.
            date_to: Конечная дата окна.

        Returns:
            Посещаемость и оценки окна по возрастанию даты урока.
        """
        ...

    async def subject_averages(
        self, student_id: UUID, date_from: date, date_to: date
    ) -> list[SubjectAverage]:
        """Считает средние оценки по предметам за период.

        Args:
            student_id: Ученик, чьи средние считаются.
            date_from: Начальная дата периода.
            date_to: Конечная дата периода.

        Returns:
            Среднее и число оценок по каждому предмету с оценками.
        """
        ...

    async def last_entry_date(self, student_id: UUID) -> date | None:
        """Возвращает дату последней записи ученика.

        Args:
            student_id: Ученик, чья последняя запись ищется.

        Returns:
            Максимальная дата посещаемости или оценки либо None,
            если записей нет.
        """
        ...
