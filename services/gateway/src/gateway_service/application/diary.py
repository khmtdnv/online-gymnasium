"""Композиторы страницы дневника: сетка недели и сводка четверти."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

from gateway_service.application.homework_list import ListMyHomeworkQuery
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.journal_client import (
    AttendanceStatus,
    DiaryEntriesResult,
    JournalClient,
    SubjectAverageEntry,
)

SCHOOL_TIMEZONE = ZoneInfo("Asia/Yekaterinburg")
MAX_LESSON_ID = 2147483647
MAX_QUARTER = 4


class GetDiaryQuery(BaseModel):
    """Ученик и опциональный понедельник недели; без него — дефолт по якорю."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    week_start: date | None

    @model_validator(mode="after")
    def valid_week(self) -> Self:
        """Неделя начинается с понедельника, если дата задана."""
        if self.week_start is not None and self.week_start.weekday() != 0:
            raise ValueError("Expected school week Monday")
        return self


class LessonSlot(BaseModel):
    """Урок сетки недели с записями и ДЗ, привязанными по due_lesson_id."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    lesson_id: int
    subject_id: int
    date: date
    starts_at: datetime
    ends_at: datetime
    status: Literal["planned", "canceled"]
    attendance: Literal["present", "absent", "unmarked"]
    absence_reason: Literal["sick", "excused", "unexcused"] | None = None
    grades: list[tuple[int, Literal["oral", "written", "control"]]] = []
    homework_status: (
        Literal["submitted", "returned", "graded", "not_submitted"] | None
    ) = None
    homework_grade: int | None = None


class DiaryWeekResult(BaseModel):
    """Сетка недели со встроенной сводкой четверти дефолтной недели."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    week_start: date
    timezone: Literal["Asia/Yekaterinburg"] = "Asia/Yekaterinburg"
    demo_cutoff: date | None
    quarter: int
    lessons: list[LessonSlot]
    summary: DiarySummaryResult


class DiarySummaryResult(BaseModel):
    """Сводка четверти: средние, четвертные оценки и пропуски."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    quarter: int
    quarter_from: date
    quarter_to: date
    subject_averages: list[SubjectAverageEntry]
    absences: list[dict]


class GetDiarySummaryQuery(BaseModel):
    """Ученик и выбранная четверть для сводки."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    quarter: int

    @model_validator(mode="after")
    def valid_quarter(self) -> Self:
        """Номер четверти в диапазоне 1–4."""
        if self.quarter not in range(1, MAX_QUARTER + 1):
            raise ValueError("Expected quarter 1 to 4")
        return self


def _monday_of(day: date) -> date:
    """Возвращает понедельник недели, содержащей день.

    Args:
        day: Любая дата недели.

    Returns:
        Понедельник той же недели.
    """
    return day - timedelta(days=day.weekday())


def _week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """Вычисляет UTC-границы школьной недели (6 дней, Пн–Сб).

    Args:
        week_start: Понедельник недели.

    Returns:
        Начало и конец недели в UTC.
    """
    start = datetime.combine(week_start, time.min, SCHOOL_TIMEZONE).astimezone(UTC)
    return start, start + timedelta(days=6)


class GetDiaryHandler:
    """Собирает страницу недели: уроки, записи, ДЗ и встроенную сводку."""

    def __init__(
        self,
        journal: JournalClient,
        schedule,
        homework: HomeworkClient,
    ) -> None:
        """Принимает клиенты с ограниченными правами чтения.

        Args:
            journal: Клиент Journal с правом diary:read.
            schedule: Клиент Schedule с чтением уроков класса.
            homework: Клиент Homework с чтением ДЗ ученика.
        """
        self._journal = journal
        self._schedule = schedule
        self._homework = homework

    async def handle(self, query: GetDiaryQuery) -> DiaryWeekResult:
        """Резолвит дефолтную неделю по якорю и собирает страницу.

        Args:
            query: Ученик и опциональный понедельник недели.

        Returns:
            Сетка недели со сводкой четверти этой недели.

        Raises:
            JournalUnavailableError: Journal недоступен.
        """
        if query.week_start is None:
            anchor = await self._journal.diary_anchor(query.student_id)
            week_start = (
                _monday_of(anchor.last_entry_date)
                if anchor.last_entry_date is not None
                else _monday_of(datetime.now(SCHOOL_TIMEZONE).date())
            )
            quarter = anchor.quarter
        else:
            anchor = await self._journal.diary_anchor(
                query.student_id, reference=query.week_start
            )
            week_start = query.week_start
            quarter = anchor.quarter

        week_from, week_until = _week_bounds(week_start)
        lessons = await self._schedule.list_calendar_lessons(
            class_id=None,
            teacher_id=None,
            starts_at_from=week_from,
            starts_at_until=week_until,
        )

        week_entries = await self._journal.list_student_entries(
            query.student_id,
            date_from=week_start,
            date_to=week_start + timedelta(days=5),
        )
        quarter_entries = await self._journal.list_student_entries(
            query.student_id, quarter=quarter
        )
        averages = await self._journal.subject_averages(query.student_id, quarter)
        homework = await self._homework.list_my_homework(
            ListMyHomeworkQuery(
                student_id=query.student_id,
                date_from=week_start,
                date_to=week_start + timedelta(days=5),
                limit=100,
            )
        )

        summary = DiarySummaryResult(
            quarter=quarter,
            quarter_from=anchor.quarter_from,
            quarter_to=anchor.quarter_to,
            subject_averages=averages,
            absences=self._collect_absences(quarter_entries),
        )

        slots = self._build_slots(lessons, week_entries, homework.items)
        return DiaryWeekResult(
            week_start=week_start,
            demo_cutoff=anchor.last_entry_date,
            quarter=quarter,
            lessons=slots,
            summary=summary,
        )

    def _collect_absences(self, entries: DiaryEntriesResult) -> list[dict]:
        """Собирает пропуски с причинами из записей окна четверти.

        Args:
            entries: Записи ученика за четверть.

        Returns:
            Список пропусков: дата, урок и причина.
        """
        absences = []
        for row in entries.attendance:
            if row.status is AttendanceStatus.PRESENT:
                continue
            absences.append(
                {
                    "lesson_id": row.lesson_id,
                    "lesson_date": row.lesson_date.isoformat(),
                    "reason": row.status.value.replace("absent_", ""),
                }
            )
        return absences

    def _build_slots(
        self, lessons, entries: DiaryEntriesResult, homework_items
    ) -> list:
        """Собирает слоты уроков с записями и ДЗ.

        Args:
            lessons: Уроки недели от Schedule.
            entries: Записи ученика за неделю.
            homework_items: ДЗ ученика за неделю от Homework.

        Returns:
            Слоты уроков с оценками, посещаемостью и статусами ДЗ.
        """
        attendance_by_lesson = {}
        for row in entries.attendance:
            attendance_by_lesson[row.lesson_id] = row
        grades_by_lesson: dict[int, list] = {}
        for row in entries.grades:
            grades_by_lesson.setdefault(row.lesson_id, []).append(row)
        homework_by_lesson = {}
        for item in homework_items:
            if item.due_lesson_id is not None:
                homework_by_lesson[item.due_lesson_id] = item

        slots = []
        for lesson in lessons:
            lesson_date = lesson.starts_at.astimezone(SCHOOL_TIMEZONE).date()
            attendance_row = attendance_by_lesson.get(lesson.id)
            if attendance_row is None:
                attendance = "unmarked"
                reason = None
            elif attendance_row.status is AttendanceStatus.PRESENT:
                attendance = "present"
                reason = None
            else:
                attendance = "absent"
                reason = attendance_row.status.value.replace("absent_", "")

            homework = homework_by_lesson.get(lesson.id)
            if homework is None:
                homework_status = None
                homework_grade = None
            elif homework.latest_answer_status is None:
                homework_status = "not_submitted"
                homework_grade = None
            else:
                homework_status = homework.latest_answer_status
                homework_grade = homework.grade

            slots.append(
                LessonSlot(
                    lesson_id=lesson.id,
                    subject_id=lesson.subject_id,
                    date=lesson_date,
                    starts_at=lesson.starts_at,
                    ends_at=lesson.ends_at,
                    status=lesson.status,
                    attendance=attendance,
                    absence_reason=reason,
                    grades=[
                        (row.grade, row.kind.value)
                        for row in grades_by_lesson.get(lesson.id, [])
                    ],
                    homework_status=homework_status,
                    homework_grade=homework_grade,
                )
            )
        return slots


class GetDiarySummaryHandler:
    """Собирает сводку четверти: средние, четвертные и пропуски."""

    def __init__(self, journal: JournalClient) -> None:
        """Принимает клиент Journal с правом diary:read.

        Args:
            journal: Клиент Journal.
        """
        self._journal = journal

    async def handle(self, query: GetDiarySummaryQuery) -> DiarySummaryResult:
        """Собирает сводку выбранной четверти.

        Args:
            query: Ученик и номер четверти.

        Returns:
            Средние, четвертные оценки и список пропусков.

        Raises:
            JournalUnavailableError: Journal недоступен.
        """
        entries = await self._journal.list_student_entries(
            query.student_id, quarter=query.quarter
        )
        averages = await self._journal.subject_averages(query.student_id, query.quarter)
        anchor = await self._journal.diary_anchor(
            query.student_id,
            reference=entries.attendance[0].lesson_date if entries.attendance else None,
        )
        return DiarySummaryResult(
            quarter=query.quarter,
            quarter_from=anchor.quarter_from,
            quarter_to=anchor.quarter_to,
            subject_averages=averages,
            absences=[
                {
                    "lesson_id": row.lesson_id,
                    "lesson_date": row.lesson_date.isoformat(),
                    "reason": row.status.value.replace("absent_", ""),
                }
                for row in entries.attendance
                if row.status is not AttendanceStatus.PRESENT
            ],
        )
