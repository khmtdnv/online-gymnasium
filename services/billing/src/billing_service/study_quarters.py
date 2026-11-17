"""Демонстрационный календарь четвертей; лето не входит в учебный год."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class StudyQuarter:
    """Период с включительным началом и исключительной границей окончания."""

    start: date
    end: date


def study_quarter_for_date(day: date) -> StudyQuarter | None:
    """Возвращает демо-четверть для даты либо None во время летнего перерыва.

    Args:
        day: Календарная дата в часовом поясе школы.

    Returns:
        Границы периода или None для июня, июля и августа.
    """
    if day.month >= 11:
        return StudyQuarter(date(day.year, 11, 1), date(day.year + 1, 1, 1))
    if day.month >= 9:
        return StudyQuarter(date(day.year, 9, 1), date(day.year, 11, 1))
    if day.month >= 6:
        return None
    if day.month >= 4:
        return StudyQuarter(date(day.year, 4, 1), date(day.year, 6, 1))
    return StudyQuarter(date(day.year, 1, 1), date(day.year, 4, 1))


def quarters_to_invoice(today: date) -> list[date]:
    """Возвращает начало текущей и следующей четверти; летом — только следующей."""
    current = study_quarter_for_date(today)
    if current is None:
        return [date(today.year, 9, 1)]
    following = date(current.end.year, 9, 1) if current.end.month == 6 else current.end
    return [current.start, following]
