"""Независимые контракты личной страницы ДЗ Gateway."""

from collections.abc import Callable
from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gateway_service.application.homework import StudentHomeworkResult
from gateway_service.application.ports.unit_of_work import UnitOfWork


class HomeworkPeriod(BaseModel):
    """Видимый период и фильтр без ID личности или класса в публичном запросе."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    date_from: date
    date_to: date
    state: Literal["all", "needs_action", "submitted", "returned", "graded"] = "all"
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        if (
            not 0 <= (self.date_to - self.date_from).days < 31
            or self.date_to == date.max
        ):
            raise ValueError("Invalid homework period")
        return self


class ListMyHomeworkQuery(HomeworkPeriod):
    """Доверенный UUID добавляется Gateway после проверки авторизации."""

    student_id: UUID


class HomeworkListItem(StudentHomeworkResult):
    """ДЗ с последним состоянием и подписями для интерфейса."""

    latest_answer_status: Literal["submitted", "returned", "graded"] | None
    grade: int | None = Field(strict=True, ge=2, le=5)
    subject_name: str = "Название предмета не задано"
    teacher_name: str = "Преподаватель не указан"


class HomeworkPageResult(BaseModel):
    """Подтверждённая страница после фильтрации всего выбранного периода."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    date_from: date
    date_to: date
    timezone: Literal["Asia/Yekaterinburg"]
    total: int = Field(strict=True, ge=0, le=1000)
    items: list[HomeworkListItem] = Field(max_length=100)


class ListMyHomeworkHandler:
    """Дополняет страницу пакетными названиями предметов и собственными ФИО."""

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], homework_client, schedule_client
    ) -> None:
        self._uow_factory = uow_factory
        self._homework = homework_client
        self._schedule = schedule_client

    async def handle(self, query: ListMyHomeworkQuery) -> HomeworkPageResult:
        """Не запрашивает отдельную историю ответа на каждую карточку."""
        page = await self._homework.list_my_homework(query)
        if not page.items:
            return page
        subjects = await self._schedule.get_subject_names(
            list({row.subject_id for row in page.items})
        )
        async with self._uow_factory() as uow:
            teachers = await uow.users.get_by_ids(
                list({row.author_id for row in page.items})
            )
        names = {
            row.id: " ".join(
                part
                for part in (row.last_name, row.first_name, row.middle_name)
                if part
            )
            for row in teachers
        }
        return page.model_copy(
            update={
                "items": [
                    row.model_copy(
                        update={
                            "subject_name": subjects.get(row.subject_id)
                            or "Название предмета не задано",
                            "teacher_name": names.get(row.author_id)
                            or "Преподаватель не указан",
                        }
                    )
                    for row in page.items
                ]
            }
        )
