from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from schedule_service.application.errors import ScheduleConflict
from schedule_service.domain.lesson import Lesson
from schedule_service.infrastructure.models.scheduled_lesson import ScheduledLessonRow


class SqlAlchemyLessonRepository:
    """Работает с уроками PostgreSQL без самостоятельного commit."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            session: Сессия текущей транзакции; commit остаётся за Unit of Work.
        """
        self._session = session

    async def list_for_teacher(
        self, *, teacher_id: UUID, date_from: date, date_to: date
    ) -> list[Lesson]:
        """Читает все свои уроки, пересекающие выбранные дни UTC.

        Args:
            teacher_id: Доверенный UUID преподавателя.
            date_from: Первая дата включительно.
            date_to: Последняя дата включительно.

        Returns:
            Уроки по starts_at,id; отменённые также включены.
        """
        range_start = datetime.combine(date_from, time.min, UTC)
        range_end = datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        statement = (
            select(ScheduledLessonRow)
            .where(
                ScheduledLessonRow.teacher_id == teacher_id,
                ScheduledLessonRow.starts_at < range_end,
                ScheduledLessonRow.ends_at > range_start,
            )
            .order_by(ScheduledLessonRow.starts_at, ScheduledLessonRow.id)
        )
        rows = (await self._session.scalars(statement)).all()
        return [
            Lesson(
                id=row.id,
                class_id=row.class_id,
                teacher_id=row.teacher_id,
                subject_id=row.subject_id,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                status=row.status,
                version=row.version,
            )
            for row in rows
        ]

    async def list_calendar_lessons(
        self,
        *,
        class_id: int | None,
        teacher_id: UUID | None,
        starts_at_from: datetime,
        starts_at_until: datetime,
    ) -> list[Lesson]:
        """Читает максимум1001строку пересекающегося интервала для явного контроля лимита."""
        owner = (
            ScheduledLessonRow.class_id == class_id
            if class_id is not None
            else ScheduledLessonRow.teacher_id == teacher_id
        )
        rows = await self._session.scalars(
            select(ScheduledLessonRow)
            .where(
                owner,
                ScheduledLessonRow.starts_at < starts_at_until,
                ScheduledLessonRow.ends_at > starts_at_from,
            )
            .order_by(ScheduledLessonRow.starts_at, ScheduledLessonRow.id)
            .limit(1001)
        )
        return [
            Lesson(
                id=row.id,
                class_id=row.class_id,
                teacher_id=row.teacher_id,
                subject_id=row.subject_id,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                status=row.status,
                version=row.version,
            )
            for row in rows
        ]

    async def add(self, lesson: Lesson) -> Lesson:
        """Добавляет урок и получает ID после flush.

        Args:
            lesson: Урок с данными для операции.

        Returns:
            Сохранённый урок с ID и значениями базы.

        Raises:
            ScheduleConflict: База отклонила запись.
        """
        row = ScheduledLessonRow(
            class_id=lesson.class_id,
            teacher_id=lesson.teacher_id,
            subject_id=lesson.subject_id,
            starts_at=lesson.starts_at,
            ends_at=lesson.ends_at,
        )

        self._session.add(row)

        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ScheduleConflict from exc

        await self._session.refresh(row)

        return Lesson(
            id=row.id,
            class_id=row.class_id,
            teacher_id=row.teacher_id,
            subject_id=row.subject_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            version=row.version,
        )

    async def get(self, lesson_id: int) -> Lesson | None:
        """Ищет урок по ID.

        Args:
            lesson_id: ID урока в базе расписания.

        Returns:
            Урок или None, если запись не найдена.
        """
        statement = select(ScheduledLessonRow).where(ScheduledLessonRow.id == lesson_id)
        scalar_result = await self._session.scalars(statement)
        row = scalar_result.one_or_none()

        if row is None:
            return None

        return Lesson(
            id=row.id,
            class_id=row.class_id,
            teacher_id=row.teacher_id,
            subject_id=row.subject_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            version=row.version,
        )

    async def get_many(self, lesson_ids: list[int]) -> list[Lesson]:
        """Читает заданные уроки одним SELECT, не отбрасывая отменённые.

        Args:
            lesson_ids: ID из проверенного пакета.

        Returns:
            Найденные уроки по возрастанию ID.
        """
        statement = (
            select(ScheduledLessonRow)
            .where(ScheduledLessonRow.id.in_(lesson_ids))
            .order_by(ScheduledLessonRow.id)
        )
        rows = (await self._session.scalars(statement)).all()
        return [
            Lesson(
                id=row.id,
                class_id=row.class_id,
                teacher_id=row.teacher_id,
                subject_id=row.subject_id,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                status=row.status,
                version=row.version,
            )
            for row in rows
        ]

    async def get_next_lesson(
        self, *, class_id: int, subject_id: int, after: datetime
    ) -> Lesson | None:
        """Читает ближайший плановый урок напрямую из авторитетной БД.

        Args:
            class_id: Класс исходного урока.
            subject_id: Предмет исходного урока.
            after: Начало исходного урока с часовым смещением.

        Returns:
            Ближайший урок либо None; отменённые не участвуют.
        """
        row = await self._session.scalar(
            select(ScheduledLessonRow)
            .where(
                ScheduledLessonRow.class_id == class_id,
                ScheduledLessonRow.subject_id == subject_id,
                ScheduledLessonRow.status == "planned",
                ScheduledLessonRow.starts_at > after,
            )
            .order_by(ScheduledLessonRow.starts_at, ScheduledLessonRow.id)
            .limit(1)
        )
        if row is None:
            return None
        return Lesson(
            id=row.id,
            class_id=row.class_id,
            teacher_id=row.teacher_id,
            subject_id=row.subject_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            version=row.version,
        )

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
        statement = (
            update(ScheduledLessonRow)
            .where(
                ScheduledLessonRow.id == lesson.id,
                ScheduledLessonRow.version == expected_version,
            )
            .values(
                starts_at=lesson.starts_at,
                ends_at=lesson.ends_at,
                version=ScheduledLessonRow.version + 1,
            )
            .returning(ScheduledLessonRow)
        )

        try:
            scalar_result = await self._session.scalars(statement)
        except IntegrityError as exc:
            raise ScheduleConflict from exc

        row = scalar_result.one_or_none()

        if row is None:
            return None

        return Lesson(
            id=row.id,
            class_id=row.class_id,
            teacher_id=row.teacher_id,
            subject_id=row.subject_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            version=row.version,
        )

    async def cancel(self, lesson: Lesson, expected_version: int) -> Lesson | None:
        """Отменяет плановый урок при совпадении ожидаемой версии.

        Args:
            lesson: Урок с данными для операции.
            expected_version: Версия урока, которую ожидает вызывающий код.

        Returns:
            Отменённый урок или None, если условия изменения не выполнены.
        """
        statement = (
            update(ScheduledLessonRow)
            .where(
                ScheduledLessonRow.id == lesson.id,
                ScheduledLessonRow.version == expected_version,
                ScheduledLessonRow.status == "planned",
            )
            .values(
                status=lesson.status,
                version=ScheduledLessonRow.version + 1,
            )
            .returning(ScheduledLessonRow)
        )

        scalar_result = await self._session.scalars(statement)
        row = scalar_result.one_or_none()

        if row is None:
            return None

        return Lesson(
            id=row.id,
            class_id=row.class_id,
            teacher_id=row.teacher_id,
            subject_id=row.subject_id,
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=row.status,
            version=row.version,
        )

    async def get_class_schedule(self, *, class_id: int, day: date) -> list[Lesson]:
        """Читает плановые уроки класса, пересекающие выбранный день UTC.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата дня UTC.

        Returns:
            Уроки по времени начала; отменённые уроки не включены.
        """
        day_start = datetime.combine(day, time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)

        statement = (
            select(ScheduledLessonRow)
            .where(
                ScheduledLessonRow.class_id == class_id,
                ScheduledLessonRow.status == "planned",
                ScheduledLessonRow.starts_at < day_end,
                ScheduledLessonRow.ends_at > day_start,
            )
            .order_by(ScheduledLessonRow.starts_at)
        )
        orm_lessons = (await self._session.scalars(statement)).all()

        domain_lessons = []
        for lesson in orm_lessons:
            domain_lessons.append(
                Lesson(
                    id=lesson.id,
                    class_id=lesson.class_id,
                    teacher_id=lesson.teacher_id,
                    subject_id=lesson.subject_id,
                    starts_at=lesson.starts_at,
                    ends_at=lesson.ends_at,
                    status=lesson.status,
                    version=lesson.version,
                )
            )

        return domain_lessons
