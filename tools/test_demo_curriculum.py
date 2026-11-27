"""Unit tests for the demo curriculum tables (tools/demo_curriculum.py)."""

import copy
import unittest

from demo_curriculum import (
    DAILY_LESSON_LIMIT,
    GRADE_CURRICULUM,
    SCHOOL_DAYS_PER_WEEK,
    SUBJECT_GRADES,
    TRUNCATION_PRIORITY,
    check_feasibility,
)

GRADES = range(1, 12)
EXPECTED_WEEKLY_TOTALS = {
    1: 20,
    2: 23,
    3: 23,
    4: 23,
    5: 27,
    6: 30,
    7: 31,
    8: 31,
    9: 33,
    10: 32,
    11: 32,
}


class DemoCurriculumTests(unittest.TestCase):
    def test_grade_hours_match_expected_totals(self):
        self.assertEqual(sorted(GRADE_CURRICULUM), list(GRADES))
        for grade, expected in EXPECTED_WEEKLY_TOTALS.items():
            self.assertEqual(sum(GRADE_CURRICULUM[grade].values()), expected, grade)

    def test_parallel_weekly_load_is_305_hours(self):
        total = sum(sum(row.values()) for row in GRADE_CURRICULUM.values())
        self.assertEqual(total, 305)

    def test_every_grade_is_feasible(self):
        check_feasibility()  # must not raise

    def test_curriculum_rows_exactly_match_subject_applicability(self):
        for grade, row in GRADE_CURRICULUM.items():
            for subject, (low, high) in SUBJECT_GRADES.items():
                self.assertEqual(subject in row, low <= grade <= high, (grade, subject))

    def test_age_boundaries(self):
        # Computer science from grade 4, physics from grade 7,
        # local studies ("окружающий мир") in grades 1-5 only.
        for grade in GRADES:
            row = GRADE_CURRICULUM[grade]
            self.assertEqual("Информатика" in row, grade >= 4, grade)
            self.assertEqual("Физика" in row, grade >= 7, grade)
            self.assertEqual("Окружающий мир" in row, grade <= 5, grade)

    def test_truncation_priority_is_full_permutation(self):
        self.assertEqual(len(TRUNCATION_PRIORITY), len(set(TRUNCATION_PRIORITY)))
        self.assertEqual(set(TRUNCATION_PRIORITY), set(SUBJECT_GRADES))

    def test_limits_cover_all_grades(self):
        self.assertEqual(
            DAILY_LESSON_LIMIT,
            {1: 4, 2: 5, 3: 5, 4: 5, 5: 6, 6: 6, 7: 7, 8: 7, 9: 7, 10: 7, 11: 7},
        )
        self.assertEqual(
            SCHOOL_DAYS_PER_WEEK,
            {grade: 5 if grade <= 4 else 6 for grade in GRADES},
        )

    def test_subject_names_match_school_catalog(self):
        from expand_demo_school import SUBJECTS

        self.assertEqual({name for _, name in SUBJECTS}, set(SUBJECT_GRADES))

    def test_check_feasibility_rejects_subject_beyond_applicability(self):
        corrupted = copy.deepcopy(GRADE_CURRICULUM)
        corrupted[1]["Физика"] = 2
        with self.assertRaises(ValueError):
            check_feasibility(grade_curriculum=corrupted)


if __name__ == "__main__":
    unittest.main()
