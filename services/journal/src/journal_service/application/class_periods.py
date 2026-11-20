"""Прикладные сценарии чтения текущего класса, истории и состава."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from journal_service.application.ports.errors import (
    ClassNotFoundError,
    CurrentPeriodNotFoundError,
)
from journal_service.application.ports.unit_of_work import UnitOfWork
from journal_service.domain.student_class_period import StudentClassPeriod

MAX_CLASS_ID = 2**31 - 1
MAX_PERIOD_OFFSET = 2**63 - 1


class GetCurrentPeriodForStudentQuery(BaseModel):
    """ID ученика, чей открытый период нужно получить."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    student_id: UUID


class ListPeriodsForStudentQuery(BaseModel):
    """ID ученика и параметры страницы его истории классов."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    student_id: UUID
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=MAX_PERIOD_OFFSET)


class ListCurrentPeriodsForClassQuery(BaseModel):
    """ID класса и параметры страницы его текущего состава."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    class_id: int = Field(ge=1, le=MAX_CLASS_ID)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=MAX_PERIOD_OFFSET)


class ClassPeriodResult(BaseModel):
    """Данные сохранённого периода для результата прикладного чтения."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: int
    student_id: UUID
    class_id: int
    joined_at: AwareDatetime
    left_at: AwareDatetime | None

    @classmethod
    def from_period(cls, period: StudentClassPeriod) -> ClassPeriodResult:
        """Преобразует доменный период с серверными полями в результат.

        Args:
            period: Период, прочитанный из репозитория.

        Returns:
            Независимый объект результата без ORM-состояния.

        Raises:
            ValueError: Репозиторий вернул период без обязательных серверных полей.
        """
        if period.id is None or period.joined_at is None:
            raise ValueError("Saved class period must have ID and joined_at")
        return cls(
            id=period.id,
            student_id=period.student_id,
            class_id=period.class_id,
            joined_at=period.joined_at,
            left_at=period.left_at,
        )


class GetCurrentPeriodForStudentHandler:
    """Получает текущий период одного ученика без обращения к Gateway."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для одного чтения.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: GetCurrentPeriodForStudentQuery) -> ClassPeriodResult:
        """Читает открытый период и дожидается завершения транзакции.

        Args:
            query: ID ученика.

        Returns:
            Данные текущего периода; не подтверждают существование учётной записи.

        Raises:
            CurrentPeriodNotFoundError: Открытого периода нет.
        """
        async with self._uow_factory() as uow:
            period = await uow.class_periods.get_current_period_for_student(
                query.student_id
            )
            if period is None:
                raise CurrentPeriodNotFoundError
        return ClassPeriodResult.from_period(period)


class ListPeriodsForStudentHandler:
    """Читает историю классов ученика, включая открытый период."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для одного чтения.
        """
        self._uow_factory = uow_factory

    async def handle(
        self, query: ListPeriodsForStudentQuery
    ) -> list[ClassPeriodResult]:
        """Читает страницу истории и сохраняет порядок репозитория.

        Args:
            query: ID ученика, размер страницы и смещение.

        Returns:
            Периоды от старых к новым; пустой список при отсутствии записей.

        """
        async with self._uow_factory() as uow:
            periods = await uow.class_periods.list_periods_for_student(
                student_id=query.student_id,
                limit=query.limit,
                offset=query.offset,
            )
        return [ClassPeriodResult.from_period(period) for period in periods]


class ListCurrentPeriodsForClassHandler:
    """Читает страницу текущего состава существующего класса."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику отдельной транзакции.

        Args:
            uow_factory: Фабрика Unit of Work для одного чтения.
        """
        self._uow_factory = uow_factory

    async def handle(
        self, query: ListCurrentPeriodsForClassQuery
    ) -> list[ClassPeriodResult]:
        """Проверяет наличие класса и читает только его открытые периоды.

        Args:
            query: ID класса, размер страницы и смещение.

        Returns:
            Текущий состав по ID периода; пустой список для пустой страницы.

        Raises:
            ClassNotFoundError: Указанный класс не существует.
        """
        async with self._uow_factory() as uow:
            school_class = await uow.classes.get_class_by_id(query.class_id)
            if school_class is None:
                raise ClassNotFoundError
            periods = await uow.class_periods.list_current_periods_for_class(
                class_id=query.class_id,
                limit=query.limit,
                offset=query.offset,
            )
        return [ClassPeriodResult.from_period(period) for period in periods]
