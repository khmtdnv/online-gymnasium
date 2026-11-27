"""Записи урока: посещаемость и оценки за урок."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from uuid import UUID

GRADE_MIN = 2
GRADE_MAX = 5


class AttendanceStatus(str, Enum):
    """Посещаемость урока одним учеником; «не отмечено» — отсутствие строки."""

    PRESENT = "present"
    ABSENT_SICK = "absent_sick"
    ABSENT_EXCUSED = "absent_excused"
    ABSENT_UNEXCUSED = "absent_unexcused"


class GradeKind(str, Enum):
    """Тип оценки за урок из закрытого словаря."""

    ORAL = "oral"
    WRITTEN = "written"
    CONTROL = "control"


def _validate_common(lesson_id: int, class_id: int) -> None:
    """Проверяет общие ключевые поля записей урока.

    Args:
        lesson_id: ID урока Schedule без внешнего ключа.
        class_id: ID класса Journal на дату урока.

    Raises:
        ValueError: ID неположительные.
    """
    if lesson_id <= 0:
        raise ValueError("Lesson ID must be positive")
    if class_id <= 0:
        raise ValueError("Class ID must be positive")


def _validate_timestamps(
    created_at: datetime | None, updated_at: datetime | None
) -> None:
    """Проверяет серверные метки времени.

    Args:
        created_at: Время создания строки, если уже назначено.
        updated_at: Время последнего изменения строки, если назначено.

    Raises:
        ValueError: Метка без известного смещения UTC.
    """
    for moment in (created_at, updated_at):
        if moment is not None and moment.utcoffset() is None:
            raise ValueError("Timestamps must have a known UTC offset")


@dataclass
class LessonAttendance:
    """Посещаемость: одна строка на (урок, ученик).

    Серверные поля (id, метки времени) появляются после сохранения.
    """

    lesson_id: int
    lesson_date: date
    class_id: int
    student_id: UUID
    status: AttendanceStatus
    author_id: UUID
    generator: bool = False
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Проверяет ключи, статус и метки времени.

        Raises:
            ValueError: Неположительные ID, статус вне enum или метка
                без смещения UTC.
        """
        _validate_common(self.lesson_id, self.class_id)
        if not isinstance(self.status, AttendanceStatus):
            raise TypeError("Attendance status must be an AttendanceStatus")
        _validate_timestamps(self.created_at, self.updated_at)

    @property
    def is_present(self) -> bool:
        """Вычисляет, был ли ученик на уроке.

        Returns:
            True только для статуса PRESENT.
        """
        return self.status is AttendanceStatus.PRESENT


@dataclass
class LessonGrade:
    """Оценка за урок: одна строка на (урок, ученик, тип)."""

    lesson_id: int
    lesson_date: date
    class_id: int
    subject_id: int
    student_id: UUID
    grade: int
    kind: GradeKind
    author_id: UUID
    generator: bool = False
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Проверяет ключи, оценку, тип и метки времени.

        Raises:
            ValueError: Неположительные ID, оценка вне 2–5, тип вне
                enum или метка без смещения UTC.
        """
        _validate_common(self.lesson_id, self.class_id)
        if self.subject_id <= 0:
            raise ValueError("Subject ID must be positive")
        if not GRADE_MIN <= self.grade <= GRADE_MAX:
            raise ValueError("Grade must be between 2 and 5")
        if not isinstance(self.kind, GradeKind):
            raise TypeError("Grade kind must be a GradeKind")
        _validate_timestamps(self.created_at, self.updated_at)
