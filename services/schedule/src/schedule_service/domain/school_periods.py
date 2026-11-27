"""Единственная конфигурация сетки семи периодов учебного дня.

Модуль не имеет зависимостей вне стандартной библиотеки: его импортируют
и сервис расписания, и инструменты демо-данных. Номер урока — конфигурация
времени, а не поле записи базы.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import TypedDict
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Yekaterinburg")
EFFECTIVE_FROM: date = date(2026, 11, 30)


class PeriodEntry(TypedDict):
    """Один период сетки в сериализуемом виде HH:MM без даты."""

    number: int
    start_at: str
    end_at: str


class SchoolPeriodsConfig(TypedDict):
    """Сериализуемая конфигурация сетки учебного дня для ответа API."""

    timezone: str
    effective_from: str
    periods: list[PeriodEntry]


@dataclass(frozen=True)
class SchoolPeriod:
    """Фиксированный интервал одного урока в местном времени школы."""

    number: int
    start_at: time
    end_at: time


PERIODS: tuple[SchoolPeriod, ...] = (
    SchoolPeriod(1, time(9, 0), time(9, 45)),
    SchoolPeriod(2, time(9, 55), time(10, 40)),
    SchoolPeriod(3, time(11, 0), time(11, 45)),
    SchoolPeriod(4, time(11, 55), time(12, 40)),
    SchoolPeriod(5, time(13, 0), time(13, 45)),
    SchoolPeriod(6, time(13, 55), time(14, 40)),
    SchoolPeriod(7, time(15, 0), time(15, 45)),
)


def period_for(starts_at: datetime, ends_at: datetime) -> SchoolPeriod | None:
    """Находит период при точном совпадении обоих краёв в местном времени.

    Args:
        starts_at: Дата и время начала урока с известным смещением UTC.
        ends_at: Дата и время конца урока с известным смещением UTC.

    Returns:
        Период сетки, которому принадлежит интервал, или None, если урок
        вне сетки или локальные даты начала и конца различаются.
    """
    local_start = starts_at.astimezone(TIMEZONE)
    local_end = ends_at.astimezone(TIMEZONE)
    if local_start.date() != local_end.date():
        return None
    for period in PERIODS:
        if local_start.time() == period.start_at and local_end.time() == period.end_at:
            return period
    return None


def school_periods_config() -> SchoolPeriodsConfig:
    """Собирает сериализуемую конфигурацию сетки для ответа API.

    Returns:
        Словарь с именем зоны школы, ISO-датой effective_from и списком
        периодов с местным временем HH:MM без даты.
    """
    return {
        "timezone": TIMEZONE.key,
        "effective_from": EFFECTIVE_FROM.isoformat(),
        "periods": [
            {
                "number": period.number,
                "start_at": period.start_at.strftime("%H:%M"),
                "end_at": period.end_at.strftime("%H:%M"),
            }
            for period in PERIODS
        ],
    }
