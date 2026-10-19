from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ScheduleChanged:
    """Событие с датами расписания класса, чей кеш нужно удалить."""

    lesson_id: int
    class_id: int
    affected_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class LessonSnapshot:
    """Состояние урока для передачи в аналитику после изменения."""

    lesson_id: int
    class_id: int
    teacher_id: UUID
    subject_id: int
    starts_at: datetime
    ends_at: datetime
    status: str
    version: int
