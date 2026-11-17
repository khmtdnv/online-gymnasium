from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from schedule_service.domain.lesson import Lesson


class LessonRepository(Protocol):
    """Контракт чтения и изменения уроков внутри текущей транзакции."""

    async def list_calendar_lessons(
        self,
        *,
        class_id: int | None,
        teacher_id: UUID | None,
        starts_at_from: datetime,
        starts_at_until: datetime,
    ) -> list[Lesson]:
        """Читает ограниченный календарный интервал, включая отменённые уроки."""
        ...

    async def list_for_teacher(
        self, *, teacher_id: UUID, date_from: date, date_to: date
    ) -> list[Lesson]:
        """Читает уроки преподавателя, пересекающие диапазон дат UTC.

        Args:
            teacher_id: Доверенный UUID преподавателя.
            date_from: Первая дата включительно.
            date_to: Последняя дата включительно.

        Returns:
            Уроки по starts_at,id, включая отменённые.
        """
        ...

    async def get_many(self, lesson_ids: list[int]) -> list[Lesson]:
        """Читает существующие уроки из пакета по возрастанию ID.

        Args:
            lesson_ids: Проверенные уникальные ID.

        Returns:
            Найденные уроки, включая отменённые.
        """
        ...

    async def get_next_lesson(
        self, *, class_id: int, subject_id: int, after: datetime
    ) -> Lesson | None:
        """Ищет ближайший плановый урок того же класса и предмета.

        Args:
            class_id: ID класса исходного урока.
            subject_id: ID его предмета.
            after: Начало исходного урока; кандидат должен быть строго позже.

        Returns:
            Первый урок по starts_at,id либо None.
        """
        ...

    async def add(self, lesson: Lesson) -> Lesson:
        """Добавляет урок и получает ID после flush.

        Args:
            lesson: Урок с данными для операции.

        Returns:
            Сохранённый урок с ID и значениями базы.

        Raises:
            ScheduleConflict: База отклонила запись.
        """
        ...

    async def get(self, lesson_id: int) -> Lesson | None:
        """Ищет урок по ID.

        Args:
            lesson_id: ID урока в базе расписания.

        Returns:
            Урок или None, если запись не найдена.
        """
        ...

    async def update(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        """Меняет интервал урока при совпадении ожидаемой версии.

        Args:
            lesson: Урок с данными для операции.
            expected_version: Версия урока, которую ожидает вызывающий код.

        Returns:
            Обновлённый урок или None, если ID/версия не совпали.

        Raises:
            ScheduleConflict: База отклонила новый интервал.
        """
        ...

    async def cancel(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        """Отменяет плановый урок при совпадении ожидаемой версии.

        Args:
            lesson: Урок с данными для операции.
            expected_version: Версия урока, которую ожидает вызывающий код.

        Returns:
            Отменённый урок или None, если условия изменения не выполнены.
        """
        ...

    async def get_class_schedule(self, *, class_id: int, day: date) -> list[Lesson]:
        """Читает плановые уроки класса, пересекающие выбранный день UTC.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата дня UTC.

        Returns:
            Уроки по времени начала; отменённые уроки не включены.
        """
        ...
