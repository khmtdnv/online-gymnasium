"""Версия-копия календаря учебного года для Journal.

Единственный источник дат — `school_calendar.py` сервиса Schedule; импорт
его кода в рантайме Journal запрещён, поэтому здесь хранится версия-копия
`QUARTERS`/`VACATIONS`/`CALENDAR_VERSION` с теми же значениями.
Синхронность копии и оригинала проверяет
`tools/test_study_quarters_sync.py`; при годовом обновлении календаря
поднимается версия и в том, и в другом модуле.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

CALENDAR_VERSION = 1

STUDY_YEAR: tuple[date, date] = (date(2026, 9, 1), date(2027, 5, 29))

QUARTERS: tuple[tuple[date, date], ...] = (
    (date(2026, 9, 1), date(2026, 10, 30)),
    (date(2026, 11, 9), date(2026, 12, 26)),
    (date(2027, 1, 11), date(2027, 3, 19)),
    (date(2027, 3, 30), date(2027, 5, 29)),
)

VACATIONS: tuple[tuple[date, date], ...] = (
    (date(2026, 10, 31), date(2026, 11, 8)),
    (date(2026, 12, 27), date(2027, 1, 10)),
    (date(2027, 3, 20), date(2027, 3, 29)),
)

SCHOOL_TIMEZONE = ZoneInfo("Asia/Yekaterinburg")

_MAX_WINDOW_DAYS: int = max((end - start).days + 1 for start, end in QUARTERS)


def _validate_copy() -> None:
    """Проверяет инварианты копии при импорте модуля.

    Raises:
        ValueError: Четверть заканчивается раньше начала, выходит за
            учебный год, пересекается с другой или каникулы
            пересекаются с четвертью.
    """
    year_start, year_end = STUDY_YEAR
    for i, (start_a, end_a) in enumerate(QUARTERS):
        if start_a > end_a:
            raise ValueError(f"quarter {start_a}..{end_a} ends before it starts")
        if not year_start <= start_a <= end_a <= year_end:
            raise ValueError(f"quarter {start_a}..{end_a} leaves the study year")
        for start_b, end_b in QUARTERS[i + 1 :]:
            if start_a <= end_b and start_b <= end_a:
                raise ValueError(
                    f"quarters {start_a}..{end_a} and {start_b}..{end_b} overlap"
                )
    for vacation_start, vacation_end in VACATIONS:
        if vacation_start > vacation_end:
            raise ValueError(
                f"vacation {vacation_start}..{vacation_end} ends before it starts"
            )
        for quarter_start, quarter_end in QUARTERS:
            if vacation_start <= quarter_end and quarter_start <= vacation_end:
                raise ValueError(
                    f"vacation {vacation_start}..{vacation_end} overlaps"
                    f" quarter {quarter_start}..{quarter_end}"
                )


_validate_copy()


def quarter_of(day: date) -> int:
    """Возвращает номер четверти, которой принадлежит дата.

    Args:
        day: Дата для определения четверти.

    Returns:
        Номер четверти от 1 до 4.

    Raises:
        ValueError: Дата вне учебного года или попала на каникулы.
    """
    for number, (start, end) in enumerate(QUARTERS, start=1):
        if start <= day <= end:
            return number
    raise ValueError(f"date {day} is outside any quarter")


def quarter_bounds(quarter: int) -> tuple[date, date]:
    """Возвращает границы четверти по её номеру.

    Args:
        quarter: Номер четверти от 1 до 4.

    Returns:
        Даты начала и конца четверти включительно.

    Raises:
        ValueError: Номер вне диапазона 1–4.
    """
    if quarter not in range(1, len(QUARTERS) + 1):
        raise ValueError("Quarter must be between 1 and 4")
    return QUARTERS[quarter - 1]


def validate_window(date_from: date, date_to: date) -> None:
    """Проверяет окно чтения дневника: порядок и размер не больше четверти.

    Args:
        date_from: Начальная дата окна включительно.
        date_to: Конечная дата окна включительно.

    Raises:
        ValueError: Конец раньше начала или окно длиннее четверти
            (чтение за весь год запрещено).
    """
    if date_to < date_from:
        raise ValueError("Window end must not be before its start")
    if (date_to - date_from).days + 1 > _MAX_WINDOW_DAYS:
        raise ValueError("Window must not be longer than a quarter")


def school_today() -> date:
    """Возвращает сегодняшнюю школьную дату в Asia/Yekaterinburg.

    Returns:
        Календарная дата текущего момента школьного часового пояса.
    """
    return datetime.now(SCHOOL_TIMEZONE).date()
