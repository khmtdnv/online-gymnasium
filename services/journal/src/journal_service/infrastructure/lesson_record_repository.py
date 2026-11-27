"""Чтение и замена записей урока через сессию SQLAlchemy."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.application.ports.lesson_record_repository import SubjectAverage
from journal_service.domain.lesson_records import (
    AttendanceStatus,
    GradeKind,
    LessonAttendance,
    LessonGrade,
)
from journal_service.infrastructure.models.lesson_record import (
    LessonAttendanceRow,
    LessonGradeRow,
)


def _to_attendance(row: LessonAttendanceRow) -> LessonAttendance:
    """Собирает доменную посещаемость из ORM-строки.

    Args:
        row: Строка таблицы lesson_attendance.

    Returns:
        Доменный объект без ORM-состояния.
    """
    return LessonAttendance(
        lesson_id=row.lesson_id,
        lesson_date=row.lesson_date,
        class_id=row.class_id,
        student_id=row.student_id,
        status=AttendanceStatus(row.status),
        author_id=row.author_id,
        generator=row.generator,
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_grade(row: LessonGradeRow) -> LessonGrade:
    """Собирает доменную оценку из ORM-строки.

    Args:
        row: Строка таблицы lesson_grades.

    Returns:
        Доменный объект без ORM-состояния.
    """
    return LessonGrade(
        lesson_id=row.lesson_id,
        lesson_date=row.lesson_date,
        class_id=row.class_id,
        subject_id=row.subject_id,
        student_id=row.student_id,
        grade=row.grade,
        kind=GradeKind(row.kind),
        author_id=row.author_id,
        generator=row.generator,
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyLessonRecordRepository:
    """Читает и заменяет записи урока в общей транзакции Unit of Work."""

    def __init__(self, session: AsyncSession) -> None:
        """Получает ту же сессию, которую используют другие репозитории UoW.

        Args:
            session: Сессия текущего Unit of Work, без самостоятельного commit.
        """
        self._session = session

    async def replace_lesson_entries(
        self,
        lesson_id: int,
        attendance: list[LessonAttendance],
        grades: list[LessonGrade],
    ) -> tuple[list[LessonAttendance], list[LessonGrade]]:
        """Заменяет записи урока содержимым пакета без commit.

        Args:
            lesson_id: Урок, записи которого заменяются.
            attendance: Посещаемость пакета на этом уроке.
            grades: Оценки пакета на этом уроке.

        Returns:
            Полное состояние записей урока после замены.
        """
        attendance_by_student = {item.student_id: item for item in attendance}
        grades_by_key = {(item.student_id, item.kind): item for item in grades}

        existing_attendance = (
            (
                await self._session.execute(
                    select(LessonAttendanceRow).where(
                        LessonAttendanceRow.lesson_id == lesson_id
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_grades = (
            (
                await self._session.execute(
                    select(LessonGradeRow).where(LessonGradeRow.lesson_id == lesson_id)
                )
            )
            .scalars()
            .all()
        )

        absent_students = {
            student_id
            for student_id, item in attendance_by_student.items()
            if item.status is not AttendanceStatus.PRESENT
        }

        for row in existing_attendance:
            item = attendance_by_student.get(row.student_id)
            if item is None:
                await self._session.delete(row)
                continue
            row.status = item.status
            row.author_id = item.author_id
            row.generator = item.generator
            row.lesson_date = item.lesson_date
            row.class_id = item.class_id

        for row in existing_grades:
            item = grades_by_key.get((row.student_id, GradeKind(row.kind)))
            if item is None or row.student_id in absent_students:
                await self._session.delete(row)
                continue
            row.grade = item.grade
            row.author_id = item.author_id
            row.generator = item.generator
            row.lesson_date = item.lesson_date
            row.class_id = item.class_id
            row.subject_id = item.subject_id

        known_attendance_students = {row.student_id for row in existing_attendance}
        for student_id, item in attendance_by_student.items():
            if student_id not in known_attendance_students:
                self._session.add(
                    LessonAttendanceRow(
                        lesson_id=item.lesson_id,
                        lesson_date=item.lesson_date,
                        class_id=item.class_id,
                        student_id=item.student_id,
                        status=item.status,
                        author_id=item.author_id,
                        generator=item.generator,
                    )
                )

        known_grade_keys = {
            (row.student_id, GradeKind(row.kind)) for row in existing_grades
        }
        for key, item in grades_by_key.items():
            if key not in known_grade_keys and key[0] not in absent_students:
                self._session.add(
                    LessonGradeRow(
                        lesson_id=item.lesson_id,
                        lesson_date=item.lesson_date,
                        class_id=item.class_id,
                        subject_id=item.subject_id,
                        student_id=item.student_id,
                        grade=item.grade,
                        kind=item.kind,
                        author_id=item.author_id,
                        generator=item.generator,
                    )
                )

        await self._session.flush()
        return await self.list_lesson_entries(lesson_id)

    async def list_lesson_entries(
        self, lesson_id: int
    ) -> tuple[list[LessonAttendance], list[LessonGrade]]:
        """Читает все записи одного урока.

        Args:
            lesson_id: Урок, записи которого читаются.

        Returns:
            Посещаемость и оценки урока по возрастанию ID строк.
        """
        attendance_rows = (
            (
                await self._session.execute(
                    select(LessonAttendanceRow)
                    .where(LessonAttendanceRow.lesson_id == lesson_id)
                    .order_by(LessonAttendanceRow.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        grade_rows = (
            (
                await self._session.execute(
                    select(LessonGradeRow)
                    .where(LessonGradeRow.lesson_id == lesson_id)
                    .order_by(LessonGradeRow.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return (
            [_to_attendance(row) for row in attendance_rows],
            [_to_grade(row) for row in grade_rows],
        )

    async def list_student_entries(
        self, student_id: UUID, date_from: date, date_to: date
    ) -> tuple[list[LessonAttendance], list[LessonGrade]]:
        """Читает записи ученика окном дат включительно.

        Args:
            student_id: Ученик, чьи записи читаются.
            date_from: Начальная дата окна.
            date_to: Конечная дата окна.

        Returns:
            Посещаемость и оценки окна по возрастанию даты урока и ID.
        """
        attendance_rows = (
            (
                await self._session.execute(
                    select(LessonAttendanceRow)
                    .where(
                        LessonAttendanceRow.student_id == student_id,
                        LessonAttendanceRow.lesson_date >= date_from,
                        LessonAttendanceRow.lesson_date <= date_to,
                    )
                    .order_by(LessonAttendanceRow.lesson_date, LessonAttendanceRow.id)
                )
            )
            .scalars()
            .all()
        )
        grade_rows = (
            (
                await self._session.execute(
                    select(LessonGradeRow)
                    .where(
                        LessonGradeRow.student_id == student_id,
                        LessonGradeRow.lesson_date >= date_from,
                        LessonGradeRow.lesson_date <= date_to,
                    )
                    .order_by(LessonGradeRow.lesson_date, LessonGradeRow.id)
                )
            )
            .scalars()
            .all()
        )
        return (
            [_to_attendance(row) for row in attendance_rows],
            [_to_grade(row) for row in grade_rows],
        )

    async def subject_averages(
        self, student_id: UUID, date_from: date, date_to: date
    ) -> list[SubjectAverage]:
        """Считает средние оценки по предметам за период.

        Args:
            student_id: Ученик, чьи средние считаются.
            date_from: Начальная дата периода.
            date_to: Конечная дата периода.

        Returns:
            Среднее и число оценок по каждому предмету по возрастанию subject_id.
        """
        rows = (
            await self._session.execute(
                select(
                    LessonGradeRow.subject_id,
                    func.avg(LessonGradeRow.grade),
                    func.count(LessonGradeRow.id),
                )
                .where(
                    LessonGradeRow.student_id == student_id,
                    LessonGradeRow.lesson_date >= date_from,
                    LessonGradeRow.lesson_date <= date_to,
                )
                .group_by(LessonGradeRow.subject_id)
                .order_by(LessonGradeRow.subject_id)
            )
        ).all()
        return [
            SubjectAverage(
                subject_id=subject_id, average=Decimal(average), grade_count=count
            )
            for subject_id, average, count in rows
        ]

    async def last_entry_date(self, student_id: UUID) -> date | None:
        """Возвращает дату последней записи ученика.

        Args:
            student_id: Ученик, чья последняя запись ищется.

        Returns:
            Максимум дат посещаемости и оценок либо None без записей.
        """
        last_attendance = await self._session.scalar(
            select(func.max(LessonAttendanceRow.lesson_date)).where(
                LessonAttendanceRow.student_id == student_id
            )
        )
        last_grade = await self._session.scalar(
            select(func.max(LessonGradeRow.lesson_date)).where(
                LessonGradeRow.student_id == student_id
            )
        )
        dates = [value for value in (last_attendance, last_grade) if value is not None]
        return max(dates) if dates else None
