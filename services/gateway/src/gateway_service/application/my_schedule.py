"""Личное расписание с названиями владельцев и единой школьной неделей."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.application.teacher_lessons import LessonInfo, TeacherLessonResult
from gateway_service.infrastructure.journal_client import JournalClient
from gateway_service.infrastructure.schedule_client import ScheduleClient

SCHOOL_TIMEZONE = ZoneInfo("Asia/Yekaterinburg")


class GetMyScheduleQuery(BaseModel):
    """Пользователь из авторизации и понедельник школьной недели."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: UUID
    role: Literal["student", "teacher"]
    week_start: date

    @model_validator(mode="after")
    def valid_week(self) -> Self:
        """Неделя начинается с понедельника и не переполняет календарь."""
        if self.week_start.weekday() != 0 or self.week_start > date(9999, 12, 24):
            raise ValueError("Expected school week Monday")
        return self


class LessonCardResult(LessonInfo):
    """Урок с настоящими названиями вместо интерфейсных ID."""

    class_name: str
    subject_name: str
    teacher_name: str


class ScheduleDay(BaseModel):
    """Один школьный день, включая день без занятий."""

    date: date
    lessons: list[LessonCardResult]


class MyScheduleResult(BaseModel):
    """Шесть дней личного календаря; отсутствие класса отличается от пустой недели."""

    week_start: date
    timezone: Literal["Asia/Yekaterinburg"] = "Asia/Yekaterinburg"
    has_class: bool = True
    days: list[ScheduleDay]


class LessonViewResult(TeacherLessonResult):
    """Две группы ДЗ с читаемыми подписями уроков для нового интерфейса."""

    lesson: LessonCardResult
    next_lesson: LessonCardResult | None


class GetMyScheduleHandler:
    """Не хранит копии классов/профилей; обогащает неделю пакетными чтениями."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal: JournalClient,
        schedule: ScheduleClient,
    ) -> None:
        self._uow_factory = uow_factory
        self._journal = journal
        self._schedule = schedule

    async def enrich_lessons(self, lessons: list[LessonInfo]) -> list[LessonCardResult]:
        """Читает имена всего набора, а не HTTP/SQL для каждого урока."""
        if not lessons:
            return []
        class_names = await self._journal.get_class_names(
            list({row.class_id for row in lessons})
        )
        subject_names = await self._schedule.get_subject_names(
            list({row.subject_id for row in lessons})
        )
        async with self._uow_factory() as uow:
            teachers = await uow.users.get_by_ids(
                list({row.teacher_id for row in lessons})
            )
        names = {
            row.id: " ".join(
                part
                for part in (row.last_name, row.first_name, row.middle_name)
                if part
            )
            for row in teachers
        }
        return [
            LessonCardResult(
                **row.model_dump(),
                class_name=class_names[row.class_id],
                subject_name=subject_names.get(row.subject_id)
                or "Название предмета не задано",
                teacher_name=names.get(row.teacher_id) or "Преподаватель не указан",
            )
            for row in lessons
        ]

    async def handle(self, query: GetMyScheduleQuery) -> MyScheduleResult:
        """Определяет класс из Journal и группирует уроки по школьной дате."""
        result = MyScheduleResult(
            week_start=query.week_start,
            days=[
                ScheduleDay(date=query.week_start + timedelta(days=i), lessons=[])
                for i in range(6)
            ],
        )
        class_id = (
            await self._journal.get_current_class_id(query.user_id)
            if query.role == "student"
            else None
        )
        if query.role == "student" and class_id is None:
            return result.model_copy(update={"has_class": False})
        start = datetime.combine(
            query.week_start, time.min, SCHOOL_TIMEZONE
        ).astimezone(UTC)
        until = start + timedelta(days=6)
        lessons = await self._schedule.list_calendar_lessons(
            class_id=class_id,
            teacher_id=query.user_id if query.role == "teacher" else None,
            starts_at_from=start,
            starts_at_until=until,
        )
        cards = await self.enrich_lessons(lessons)
        by_day = {day.date: day for day in result.days}
        for card in cards:
            day = card.starts_at.astimezone(SCHOOL_TIMEZONE).date()
            if day in by_day:
                by_day[day].lessons.append(card)
        return result
