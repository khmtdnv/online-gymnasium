"""Проверяет три прикладных чтения периодов без HTTP и реальной БД."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from journal_service.domain.school_class import Class
from journal_service.domain.student_class_period import StudentClassPeriod

STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
JOINED_AT = datetime(2026, 9, 1, 9, tzinfo=UTC)


def make_period(period_id: int = 10, *, closed: bool = False) -> StudentClassPeriod:
    """Готовит доменный период с серверными полями и известной датой."""
    return StudentClassPeriod(
        id=period_id,
        student_id=STUDENT_ID,
        class_id=7,
        joined_at=JOINED_AT,
        left_at=JOINED_AT if closed else None,
    )


def make_uow() -> tuple[Mock, Mock]:
    """Подменяет границу БД, сохраняя отдельные проверяемые операции чтения."""
    uow = Mock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.class_periods.get_current_period_for_student = AsyncMock(
        return_value=make_period()
    )
    uow.class_periods.list_periods_for_student = AsyncMock(
        return_value=[make_period(20, closed=True), make_period(10)]
    )
    uow.classes.get_class_by_id = AsyncMock(
        return_value=Class(name="7А", study_year=2026, id=7, created_at=JOINED_AT)
    )
    uow.class_periods.list_current_periods_for_class = AsyncMock(
        return_value=[make_period(10), make_period(20)]
    )
    return uow, Mock(return_value=uow)


@pytest.mark.parametrize("missing_field", ["id", "joined_at"])
def test_result_rejects_period_without_server_fields(missing_field: str) -> None:
    """Не выдаёт несохранённый объект репозитория за корректный результат чтения."""
    from journal_service.application.class_periods import ClassPeriodResult

    period = make_period()
    setattr(period, missing_field, None)
    with pytest.raises(ValueError):
        ClassPeriodResult.from_period(period)


def test_current_period_returns_result_after_unit_of_work_exits() -> None:
    """Читает одного ученика и отдаёт DTO, а не доменный объект."""
    from journal_service.application.class_periods import (
        ClassPeriodResult,
        GetCurrentPeriodForStudentHandler,
        GetCurrentPeriodForStudentQuery,
    )

    uow, factory = make_uow()
    result = asyncio.run(
        GetCurrentPeriodForStudentHandler(factory).handle(
            GetCurrentPeriodForStudentQuery(student_id=STUDENT_ID)
        )
    )
    assert result == ClassPeriodResult(
        id=10, student_id=STUDENT_ID, class_id=7, joined_at=JOINED_AT, left_at=None
    )
    uow.class_periods.get_current_period_for_student.assert_awaited_once_with(
        STUDENT_ID
    )
    uow.__aexit__.assert_awaited_once_with(None, None, None)


def test_missing_current_period_is_not_found() -> None:
    """Отсутствие открытого периода не маскируется под пустой успешный объект."""
    from journal_service.application.class_periods import (
        GetCurrentPeriodForStudentHandler,
        GetCurrentPeriodForStudentQuery,
    )
    from journal_service.application.ports.errors import CurrentPeriodNotFoundError

    uow, factory = make_uow()
    uow.class_periods.get_current_period_for_student.return_value = None
    with pytest.raises(CurrentPeriodNotFoundError):
        asyncio.run(
            GetCurrentPeriodForStudentHandler(factory).handle(
                GetCurrentPeriodForStudentQuery(student_id=STUDENT_ID)
            )
        )


@pytest.mark.parametrize("empty", [False, True])
def test_history_passes_pagination_and_preserves_periods(empty: bool) -> None:
    """Сохраняет порядок и закрытые периоды репозитория; отсутствие истории допустимо."""
    from journal_service.application.class_periods import (
        ListPeriodsForStudentHandler,
        ListPeriodsForStudentQuery,
    )

    uow, factory = make_uow()
    if empty:
        uow.class_periods.list_periods_for_student.return_value = []
    result = asyncio.run(
        ListPeriodsForStudentHandler(factory).handle(
            ListPeriodsForStudentQuery(student_id=STUDENT_ID, limit=2, offset=1)
        )
    )
    assert [period.id for period in result] == ([] if empty else [20, 10])
    if not empty:
        assert result[0].left_at == JOINED_AT
        assert result[1].left_at is None
    uow.class_periods.list_periods_for_student.assert_awaited_once_with(
        student_id=STUDENT_ID, limit=2, offset=1
    )
    uow.classes.get_class_by_id.assert_not_awaited()


@pytest.mark.parametrize("empty", [False, True])
def test_class_roster_checks_class_and_returns_page(empty: bool) -> None:
    """Отличает существующий пустой класс от неизвестного и сохраняет страницу."""
    from journal_service.application.class_periods import (
        ListCurrentPeriodsForClassHandler,
        ListCurrentPeriodsForClassQuery,
    )

    uow, factory = make_uow()
    if empty:
        uow.class_periods.list_current_periods_for_class.return_value = []
    result = asyncio.run(
        ListCurrentPeriodsForClassHandler(factory).handle(
            ListCurrentPeriodsForClassQuery(class_id=7, limit=2, offset=1)
        )
    )
    assert [period.id for period in result] == ([] if empty else [10, 20])
    uow.classes.get_class_by_id.assert_awaited_once_with(7)
    uow.class_periods.list_current_periods_for_class.assert_awaited_once_with(
        class_id=7, limit=2, offset=1
    )


def test_missing_class_does_not_query_roster() -> None:
    """Возвращает ожидаемую ошибку до чтения состава несуществующего класса."""
    from journal_service.application.class_periods import (
        ListCurrentPeriodsForClassHandler,
        ListCurrentPeriodsForClassQuery,
    )
    from journal_service.application.ports.errors import ClassNotFoundError

    uow, factory = make_uow()
    uow.classes.get_class_by_id.return_value = None
    with pytest.raises(ClassNotFoundError):
        asyncio.run(
            ListCurrentPeriodsForClassHandler(factory).handle(
                ListCurrentPeriodsForClassQuery(class_id=7)
            )
        )
    uow.class_periods.list_current_periods_for_class.assert_not_awaited()


@pytest.mark.parametrize("scenario", ["current", "history", "roster"])
def test_read_does_not_return_success_if_uow_exit_fails(scenario: str) -> None:
    """Все чтения дожидаются завершения UoW и не скрывают ошибку выхода."""
    from journal_service.application import class_periods as module

    uow, factory = make_uow()
    failure = RuntimeError("transaction close failed")
    uow.__aexit__.side_effect = failure
    handler, query = {
        "current": (
            module.GetCurrentPeriodForStudentHandler(factory),
            module.GetCurrentPeriodForStudentQuery(student_id=STUDENT_ID),
        ),
        "history": (
            module.ListPeriodsForStudentHandler(factory),
            module.ListPeriodsForStudentQuery(student_id=STUDENT_ID),
        ),
        "roster": (
            module.ListCurrentPeriodsForClassHandler(factory),
            module.ListCurrentPeriodsForClassQuery(class_id=7),
        ),
    }[scenario]
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(handler.handle(query))
    assert caught.value is failure


@pytest.mark.parametrize("scenario", ["history", "roster"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("limit", 0),
        ("limit", 101),
        ("limit", True),
        ("limit", "2"),
        ("offset", -1),
        ("offset", 2**63),
        ("offset", False),
        ("offset", 1.5),
    ],
)
def test_invalid_page_is_rejected_before_uow(scenario: str, field: str, value) -> None:
    """Защищает прямой вызов application от неверных размеров страницы."""
    from pydantic import ValidationError

    from journal_service.application import class_periods as module

    factory = Mock()
    kwargs = {field: value}
    if scenario == "history":
        handler = module.ListPeriodsForStudentHandler(factory)
        constructor = module.ListPeriodsForStudentQuery
        kwargs["student_id"] = STUDENT_ID
    else:
        handler = module.ListCurrentPeriodsForClassHandler(factory)
        constructor = module.ListCurrentPeriodsForClassQuery
        kwargs["class_id"] = 7
    with pytest.raises(ValidationError):
        asyncio.run(handler.handle(constructor(**kwargs)))
    factory.assert_not_called()


@pytest.mark.parametrize("class_id", [0, -1, 2**31, True, "7"])
def test_invalid_class_id_is_rejected_before_uow(class_id) -> None:
    """Не отправляет в PostgreSQL ID вне диапазона положительного INTEGER."""
    from pydantic import ValidationError

    from journal_service.application.class_periods import (
        ListCurrentPeriodsForClassHandler,
        ListCurrentPeriodsForClassQuery,
    )

    factory = Mock()
    with pytest.raises(ValidationError):
        asyncio.run(
            ListCurrentPeriodsForClassHandler(factory).handle(
                ListCurrentPeriodsForClassQuery(class_id=class_id)
            )
        )
    factory.assert_not_called()


@pytest.mark.parametrize("scenario", ["current", "history"])
def test_invalid_student_id_is_rejected_before_uow(scenario: str) -> None:
    """Внутренний сценарий требует UUID, а не необработанную строку."""
    from pydantic import ValidationError

    from journal_service.application import class_periods as module

    factory = Mock()
    handler, constructor = (
        (
            module.GetCurrentPeriodForStudentHandler(factory),
            module.GetCurrentPeriodForStudentQuery,
        )
        if scenario == "current"
        else (
            module.ListPeriodsForStudentHandler(factory),
            module.ListPeriodsForStudentQuery,
        )
    )
    with pytest.raises(ValidationError):
        asyncio.run(handler.handle(constructor(student_id="not-a-uuid")))
    factory.assert_not_called()
