"""Личный список ДЗ с фильтром по актуальному сроку и последнему ответу."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from homework_service.application.homework_results import (
    StudentHomeworkResult,
    _resolve_deadlines,
)
from homework_service.application.ports.errors import OwnerLookupUnavailableError
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.application.ports.unit_of_work import UnitOfWork

SCHOOL_TIMEZONE = ZoneInfo("Asia/Yekaterinburg")


class ListMyHomeworkQuery(BaseModel):
    """Доверенный ученик и явно ограниченный период; фильтр предшествует странице."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    date_from: date
    date_to: date
    state: Literal["all", "needs_action", "submitted", "returned", "graded"] = "all"
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        """Отклоняет обратный диапазон, больше31дня и переполнение правой границы."""
        if (
            not 0 <= (self.date_to - self.date_from).days < 31
            or self.date_to == date.max
        ):
            raise ValueError("Invalid homework period")
        return self


class HomeworkListItem(StudentHomeworkResult):
    """Только итоговое состояние последней попытки, без выгрузки всей истории."""

    latest_answer_status: Literal["submitted", "returned", "graded"] | None
    grade: int | None = Field(strict=True, ge=2, le=5)


class HomeworkPageResult(BaseModel):
    """Страница полного отфильтрованного выбранного периода, не всего архива."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    date_from: date
    date_to: date
    timezone: Literal["Asia/Yekaterinburg"] = "Asia/Yekaterinburg"
    total: int = Field(ge=0)
    items: list[HomeworkListItem]


class ListMyHomeworkHandler:
    """Получает ограниченные кандидаты и последние попытки пакетно без N+1."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal_reader: JournalReader,
        schedule_reader: ScheduleReader,
    ) -> None:
        self._uow_factory = uow_factory
        self._journal_reader = journal_reader
        self._schedule_reader = schedule_reader

    async def handle(self, query: ListMyHomeworkQuery) -> HomeworkPageResult:
        """Проверяет класс, вычисляет сроки, фильтрует и только потом берёт страницу."""
        empty = HomeworkPageResult(
            date_from=query.date_from, date_to=query.date_to, total=0, items=[]
        )
        class_id = await self._journal_reader.get_current_class_id(query.student_id)
        if class_id is None:
            return empty
        start = datetime.combine(query.date_from, time.min, SCHOOL_TIMEZONE)
        until = datetime.combine(
            query.date_to + timedelta(days=1), time.min, SCHOOL_TIMEZONE
        )
        lessons = await self._schedule_reader.list_calendar_lessons(
            class_id=class_id, starts_at_from=start, starts_at_until=until
        )
        by_id = {row.id: row for row in lessons}
        if len(by_id) != len(lessons) or any(
            row.class_id != class_id for row in lessons
        ):
            raise OwnerLookupUnavailableError("Calendar class mismatch")
        # Урок может пересекать полночь школы. Для срока нужна дата его начала,
        # а не дата окончания: пограничная строка предыдущего дня не входит в период.
        by_id = {
            lesson_id: row
            for lesson_id, row in by_id.items()
            if start <= row.starts_at < until
        }
        async with self._uow_factory() as uow:
            pairs = await uow.homeworks.list_for_period(
                class_id=class_id,
                student_id=query.student_id,
                starts_at_from=start,
                starts_at_until=until,
                due_lesson_ids=list(by_id),
            )
            if len(pairs) > 1000:
                raise ValueError("Too many homework assignments; narrow the period")
            homeworks = [row for row, _ in pairs]
            if any(row.class_id != class_id for row in homeworks):
                raise OwnerLookupUnavailableError("Homework class mismatch")
            files = (
                await uow.files.list_for_homeworks([row.id for row in homeworks])
                if homeworks
                else {}
            )
        resolved = await _resolve_deadlines(
            homeworks, self._schedule_reader, files, due_lessons=by_id
        )
        items = []
        for row, (_, answer) in zip(resolved, pairs, strict=True):
            state = answer.status if answer else None
            if query.state == "needs_action" and state not in (None, "returned"):
                continue
            if query.state not in ("all", "needs_action") and state != query.state:
                continue
            items.append(
                HomeworkListItem(
                    **row.model_dump(),
                    latest_answer_status=state,
                    grade=answer.grade if answer else None,
                )
            )
        items.sort(
            key=lambda row: (
                row.final_due_datetime or datetime.max.replace(tzinfo=UTC),
                row.id,
            )
        )
        return empty.model_copy(
            update={
                "total": len(items),
                "items": items[query.offset : query.offset + query.limit],
            }
        )
