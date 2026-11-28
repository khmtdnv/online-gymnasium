"""Синхронность копии Journal и календаря Schedule.

Копия `journal_service/domain/study_quarters.py` обязана совпадать с
`schedule_service/domain/school_calendar.py` по четвертям, каникулам,
границам года и версии календаря: рассинхрон ломает окно чтения
дневника и гарды записи. Импорт в тесте — не рантайм-связь (внутри
контейнера Journal модуль Schedule недоступен), это именно проверка
копии против оригинала.
"""

import sys
import unittest
from pathlib import Path

_JOURNAL_SRC = str(Path(__file__).resolve().parents[1] / "services" / "journal" / "src")
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_JOURNAL_SRC, _SCHEDULE_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from journal_service.domain import study_quarters
from schedule_service.domain import school_calendar


class StudyQuartersSyncTest(unittest.TestCase):
    def test_copy_equals_school_calendar(self):
        self.assertEqual(study_quarters.QUARTERS, school_calendar.QUARTERS)
        self.assertEqual(study_quarters.VACATIONS, school_calendar.VACATIONS)
        self.assertEqual(study_quarters.STUDY_YEAR, school_calendar.STUDY_YEAR)
        self.assertEqual(
            study_quarters.CALENDAR_VERSION, school_calendar.CALENDAR_VERSION
        )

    def test_quarter_of_agrees_on_quarter_dates(self):
        for number, (start, end) in enumerate(school_calendar.QUARTERS, start=1):
            self.assertEqual(study_quarters.quarter_of(start), number)
            self.assertEqual(study_quarters.quarter_of(end), number)


if __name__ == "__main__":
    unittest.main()
