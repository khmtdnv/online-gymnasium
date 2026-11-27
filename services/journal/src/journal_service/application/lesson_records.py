"""Прикладные сценарии записей урока: запись учителя и чтения дневника."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from journal_service.application.ports.unit_of_work import UnitOfWork
from journal_service.domain.lesson_records import (
    GRADE_MAX,
    GRADE_MIN,
    AttendanceStatus,
    GradeKind,
    LessonAttendance,
    LessonGrade,
)
from journal_service.domain.study_quarters import (
    quarter_bounds,
    quarter_of,
    school_today,
    validate_window,
)

MAX_LESSON_ID = 2**31 - 1
MAX_QUARTER = 4
MAX_ATTENDANCE_ENTRIES = 50
MAX_GRADE_ENTRIES = 100
MAX_GRADES_PER_STUDENT = 2


class LessonRecordValidationError(Exception):
    """Нарушение прикладных правил записи урока; отображается как 422."""


class LessonRecordConflictError(Exception):
    """Несовпадение учителя контекста урока с автором команды; 409."""


class AttendanceEntry(BaseModel):
    """Посещаемость одного ученика в пакете записи урока."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    student_id: UUID
    status: AttendanceStatus


class GradeEntry(BaseModel):
    """Оценка одного ученика в пакете записи урока."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    student_id: UUID
    kind: GradeKind
    grade: int = Field(strict=True, ge=GRADE_MIN, le=GRADE_MAX)


class LessonContext(BaseModel):
    """Провалидированный Gateway'ем контекст урока в команде записи."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    class_id: int = Field(strict=True, ge=1, le=MAX_LESSON_ID)
    subject_id: int = Field(strict=True, ge=1, le=MAX_LESSON_ID)
    lesson_date: date
    status: Literal["planned"]
    teacher_id: UUID


class RecordLessonEntriesCommand(BaseModel):
    """Пакет замены записей одного урока."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lesson_id: int = Field(strict=True, ge=1, le=MAX_LESSON_ID)
    context: LessonContext
    attendance: list[AttendanceEntry] = Field(
        max_length=MAX_ATTENDANCE_ENTRIES, default_factory=list
    )
    grades: list[GradeEntry] = Field(max_length=MAX_GRADE_ENTRIES, default_factory=list)


class AttendanceResult(BaseModel):
    """Сохранённая посещаемость одного ученика."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    lesson_id: int
    lesson_date: date
    class_id: int
    student_id: UUID
    status: AttendanceStatus
    author_id: UUID
    generator: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class GradeResult(BaseModel):
    """Сохранённая оценка одного ученика."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    lesson_id: int
    lesson_date: date
    class_id: int
    subject_id: int
    student_id: UUID
    grade: int
    kind: GradeKind
    author_id: UUID
    generator: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class LessonEntriesResult(BaseModel):
    """Записи урока или окна дат для отображения и формы правки."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    attendance: list[AttendanceResult]
    grades: list[GradeResult]

    @classmethod
    def from_entries(
        cls, attendance: list[LessonAttendance], grades: list[LessonGrade]
    ) -> LessonEntriesResult:
        """Преобразует доменные записи с серверными полями в результат.

        Args:
            attendance: Посещаемость, прочитанная после сохранения.
            grades: Оценки, прочитанные после сохранения.

        Returns:
            Независимый результат без ORM-состояния.

        Raises:
            ValueError: Запись без серверных полей после сохранения.
        """
        attendance_results = []
        for item in attendance:
            if item.id is None or item.created_at is None or item.updated_at is None:
                raise ValueError("Saved attendance must have server fields")
            attendance_results.append(
                AttendanceResult(
                    lesson_id=item.lesson_id,
                    lesson_date=item.lesson_date,
                    class_id=item.class_id,
                    student_id=item.student_id,
                    status=item.status,
                    author_id=item.author_id,
                    generator=item.generator,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            )
        grade_results = []
        for item in grades:
            if item.id is None or item.created_at is None or item.updated_at is None:
                raise ValueError("Saved grade must have server fields")
            grade_results.append(
                GradeResult(
                    lesson_id=item.lesson_id,
                    lesson_date=item.lesson_date,
                    class_id=item.class_id,
                    subject_id=item.subject_id,
                    student_id=item.student_id,
                    grade=item.grade,
                    kind=item.kind,
                    author_id=item.author_id,
                    generator=item.generator,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            )
        return cls(attendance=attendance_results, grades=grade_results)


class SubjectAverageResult(BaseModel):
    """Средняя оценка по предмету за период и четвертная оценка."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    subject_id: int
    average: Decimal
    grade_count: int
    quarter_grade: int


class LastEntryDateResult(BaseModel):
    """Якорь дневника: последняя запись и четверть опорной даты."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    last_entry_date: date | None
    quarter: int = Field(strict=True, ge=1, le=MAX_QUARTER)
    quarter_from: date
    quarter_to: date


def _round_half_up(value: Decimal) -> int:
    """Округляет среднюю к ближайшему целому по правилу half-up.

    Args:
        value: Средняя оценка по предмету.

    Returns:
        Четвертная оценка в диапазоне 2–5.
    """
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


class RecordLessonEntriesHandler:
    """Заменяет записи урока пакетом учителя одной транзакцией."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для команды записи.
        """
        self._uow_factory = uow_factory

    async def handle(
        self, command: RecordLessonEntriesCommand, actor_id: UUID
    ) -> LessonEntriesResult:
        """Проверяет правила записи и заменяет записи урока пакетом.

        Args:
            command: Пакет с контекстом урока, посещаемостью и оценками.
            actor_id: Учитель из заголовка X-User-ID.

        Returns:
            Полное состояние записей урока после замены.

        Raises:
            LessonRecordConflictError: Учитель контекста не совпадает
                с автором команды.
            LessonRecordValidationError: Будущий урок, закрытая четверть,
                дубли учеников или типов, оценки вне состава или не
                присутствующим, более двух оценок ученику.
        """
        context = command.context

        if context.teacher_id != actor_id:
            raise LessonRecordConflictError("Lesson teacher does not match actor")

        today = school_today()
        if context.lesson_date > today:
            raise LessonRecordValidationError("Lesson date is in the future")

        try:
            lesson_quarter = quarter_of(context.lesson_date)
            current_quarter = quarter_of(today)
        except ValueError as exc:
            raise LessonRecordValidationError(
                "Lesson date is outside the study year"
            ) from exc
        if lesson_quarter != current_quarter:
            raise LessonRecordValidationError("Lesson belongs to a closed quarter")

        if len({entry.student_id for entry in command.attendance}) != len(
            command.attendance
        ):
            raise LessonRecordValidationError("Duplicate attendance student")

        grades_by_student: defaultdict[UUID, list[GradeEntry]] = defaultdict(list)
        grade_keys = {(entry.student_id, entry.kind) for entry in command.grades}
        if len(grade_keys) != len(command.grades):
            raise LessonRecordValidationError("Duplicate grade kind for student")
        for entry in command.grades:
            grades_by_student[entry.student_id].append(entry)
            if len(grades_by_student[entry.student_id]) > MAX_GRADES_PER_STUDENT:
                raise LessonRecordValidationError("Too many grades for student")

        attendance_status = {
            entry.student_id: entry.status for entry in command.attendance
        }
        for entry in command.grades:
            if entry.student_id not in attendance_status:
                raise LessonRecordValidationError("Grade without attendance")

        async with self._uow_factory() as uow:
            members = await uow.class_periods.list_members_on_date(
                context.class_id, context.lesson_date
            )
            roster = {period.student_id for period in members}

            for student_id in attendance_status:
                if student_id not in roster:
                    raise LessonRecordValidationError("Student is not in class roster")
            for entry in command.grades:
                if entry.student_id not in roster:
                    raise LessonRecordValidationError("Student is not in class roster")
                if attendance_status[entry.student_id] is not AttendanceStatus.PRESENT:
                    raise LessonRecordValidationError("Grade for absent student")

            attendance_domain = [
                LessonAttendance(
                    lesson_id=command.lesson_id,
                    lesson_date=context.lesson_date,
                    class_id=context.class_id,
                    student_id=student_id,
                    status=status,
                    author_id=actor_id,
                )
                for student_id, status in attendance_status.items()
            ]
            grades_domain = [
                LessonGrade(
                    lesson_id=command.lesson_id,
                    lesson_date=context.lesson_date,
                    class_id=context.class_id,
                    subject_id=context.subject_id,
                    student_id=entry.student_id,
                    grade=entry.grade,
                    kind=entry.kind,
                    author_id=actor_id,
                )
                for entry in command.grades
            ]

            (
                saved_attendance,
                saved_grades,
            ) = await uow.lesson_records.replace_lesson_entries(
                command.lesson_id, attendance_domain, grades_domain
            )

        return LessonEntriesResult.from_entries(saved_attendance, saved_grades)


class ListStudentDiaryEntriesHandler:
    """Читает записи ученика окном не длиннее четверти."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для чтения.
        """
        self._uow_factory = uow_factory

    async def handle(
        self,
        student_id: UUID,
        date_from: date | None,
        date_to: date | None,
        quarter: int | None = None,
    ) -> LessonEntriesResult:
        """Проверяет окно и читает записи ученика.

        Окно задаётся либо датами (не длиннее четверти), либо номером
        четверти — тогда границы вычисляет Journal из своей копии
        календаря, и вызывающий сервис календаря не знает.

        Args:
            student_id: Ученик, чьи записи читаются.
            date_from: Начальная дата окна включительно.
            date_to: Конечная дата окна включительно.
            quarter: Номер четверти вместо дат окна.

        Returns:
            Посещаемость и оценки окна.

        Raises:
            LessonRecordValidationError: Окно длиннее четверти, кончается
                раньше начала, задано двумя способами сразу или номер
                четверти вне 1–4.
        """
        if quarter is not None:
            if date_from is not None or date_to is not None:
                raise LessonRecordValidationError(
                    "Window must be set either by dates or by quarter"
                )
            try:
                date_from, date_to = quarter_bounds(quarter)
            except ValueError as exc:
                raise LessonRecordValidationError("Invalid quarter") from exc
        else:
            if date_from is None or date_to is None:
                raise LessonRecordValidationError("Window dates are required")
            try:
                validate_window(date_from, date_to)
            except ValueError as exc:
                raise LessonRecordValidationError("Invalid diary window") from exc

        async with self._uow_factory() as uow:
            attendance, grades = await uow.lesson_records.list_student_entries(
                student_id, date_from, date_to
            )
        return LessonEntriesResult.from_entries(attendance, grades)


class GetSubjectAveragesHandler:
    """Считает средние оценки по предметам за четверть."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для чтения.
        """
        self._uow_factory = uow_factory

    async def handle(
        self, student_id: UUID, quarter: int
    ) -> list[SubjectAverageResult]:
        """Возвращает средние и четвертные оценки выбранной четверти.

        Args:
            student_id: Ученик, чьи средние считаются.
            quarter: Номер четверти от 1 до 4.

        Returns:
            Средняя, число оценок и четвертная по каждому предмету.

        Raises:
            LessonRecordValidationError: Номер четверти вне 1–4.
        """
        try:
            date_from, date_to = quarter_bounds(quarter)
        except ValueError as exc:
            raise LessonRecordValidationError("Invalid quarter") from exc

        async with self._uow_factory() as uow:
            averages = await uow.lesson_records.subject_averages(
                student_id, date_from, date_to
            )
        return [
            SubjectAverageResult(
                subject_id=average.subject_id,
                average=average.average,
                grade_count=average.grade_count,
                quarter_grade=_round_half_up(average.average),
            )
            for average in averages
        ]


class GetLastEntryDateHandler:
    """Возвращает дату последней записи ученика."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для чтения.
        """
        self._uow_factory = uow_factory

    async def handle(
        self, student_id: UUID, reference: date | None = None
    ) -> LastEntryDateResult:
        """Читает якорь дневника: последнюю запись и четверть.

        Четверть вычисляется от опорной даты: явной ссылки, иначе
        последней записи, иначе сегодняшней школьной даты. Календарь
        знает только Journal — вызывающие сервисы копию не хранят.

        Args:
            student_id: Ученик, чья последняя запись ищется.
            reference: Опорная дата четверти, если вызвана с ней.

        Returns:
            Дата последней записи (None без записей), номер и границы
            четверти опорной даты.

        Raises:
            LessonRecordValidationError: Опорная дата вне учебного года.
        """
        async with self._uow_factory() as uow:
            last_entry_date = await uow.lesson_records.last_entry_date(student_id)
        base = reference or last_entry_date or school_today()
        try:
            quarter = quarter_of(base)
            quarter_from, quarter_to = quarter_bounds(quarter)
        except ValueError as exc:
            raise LessonRecordValidationError(
                "Reference date is outside the study year"
            ) from exc
        return LastEntryDateResult(
            last_entry_date=last_entry_date,
            quarter=quarter,
            quarter_from=quarter_from,
            quarter_to=quarter_to,
        )


class ListLessonEntriesHandler:
    """Читает записи одного урока для формы правки."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для чтения.
        """
        self._uow_factory = uow_factory

    async def handle(self, lesson_id: int) -> LessonEntriesResult:
        """Читает посещаемость и оценки урока.

        Args:
            lesson_id: Урок, записи которого читаются.

        Returns:
            Записи урока; пустые списки без записей.
        """
        async with self._uow_factory() as uow:
            attendance, grades = await uow.lesson_records.list_lesson_entries(lesson_id)
        return LessonEntriesResult.from_entries(attendance, grades)
