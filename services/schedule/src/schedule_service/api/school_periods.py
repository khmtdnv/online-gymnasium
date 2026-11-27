"""Сетка семи школьных периодов для доверенного Gateway."""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from schedule_service.api.teacher_lessons import require_gateway
from schedule_service.domain.school_periods import school_periods_config


class SchoolPeriodItem(BaseModel):
    """Один период учебного дня в местном времени школы без даты."""

    number: int
    start_at: str
    end_at: str


class SchoolPeriodsResponse(BaseModel):
    """Неизменяемая конфигурация сетки учебного дня."""

    timezone: str
    effective_from: date
    periods: list[SchoolPeriodItem]


router = APIRouter(
    prefix="/internal/school-periods",
    include_in_schema=False,
    dependencies=[Depends(require_gateway)],
)


@router.get("", response_model=SchoolPeriodsResponse)
async def read_school_periods() -> SchoolPeriodsResponse:
    """Отдаёт конфигурацию периодов из домена без обращения к базе.

    Returns:
        Зона школы, дата effective_from и все семь периодов HH:MM.
    """
    return SchoolPeriodsResponse(**school_periods_config())
