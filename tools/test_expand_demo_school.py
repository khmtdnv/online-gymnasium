"""Checks of the expanded demo school composition (accounts per curriculum)."""

import unittest

from demo_curriculum import GRADE_CURRICULUM, SUBJECT_GRADES
from expand_demo_school import (
    CODES,
    LETTERS,
    STUDENTS_PER_CLASS,
    SUBJECTS,
    applicable_subject_ids,
    emails,
    expansion_accounts,
    subject_teacher_email,
)

PHYSICS_ID = 1006
INFORMATICS_ID = 1008
MATHEMATICS_ID = 1


class ExpandedSchoolAccounts(unittest.TestCase):
    """The staff follows SUBJECT_GRADES x GRADE_CURRICULUM, not the full catalog."""

    @classmethod
    def setUpClass(cls):
        cls.accounts = expansion_accounts()
        cls.emails = {account["email"] for account in cls.accounts}
        cls.id_of_name = {name: subject_id for subject_id, name in SUBJECTS}

    def test_accounts_are_unique(self):
        self.assertEqual(len(self.accounts), len(self.emails))
        self.assertEqual(emails(1, "a"), "teacher01@demo.og.test")
        self.assertEqual(emails(1, "a", 1), "student01.1@demo.og.test")
        self.assertEqual(len(CODES), len(LETTERS))

    def test_every_grade_line_is_complete(self):
        # One class teacher plus ten students per class line, and one
        # subject account per applicable subject of the grade.
        expected = sum(
            5 * (1 + len(applicable_subject_ids(grade)) + STUDENTS_PER_CLASS)
            for grade in range(1, 12)
        )
        self.assertEqual(len(self.accounts), expected)

    def test_applicable_subjects_follow_the_curriculum(self):
        for grade in range(1, 12):
            with self.subTest(grade=grade):
                ids = applicable_subject_ids(grade)
                expected_names = set(GRADE_CURRICULUM[grade]) - {"Математика"}
                self.assertEqual(
                    {name for subject_id, name in SUBJECTS if subject_id in ids},
                    expected_names,
                )

    def test_teacher_accounts_match_subject_grades(self):
        # An account exists exactly when the subject has hours in the
        # grade: no physics before grade 7, no informatics before
        # grade 4, no English in grade 1.
        for grade in range(1, 12):
            for subject_id, name in SUBJECTS:
                if subject_id == MATHEMATICS_ID:
                    continue  # the class line teacher owns mathematics
                low, high = SUBJECT_GRADES[name]
                applicable = low <= grade <= high and name in GRADE_CURRICULUM[grade]
                for code in CODES:
                    email = subject_teacher_email(grade, code, subject_id)
                    self.assertEqual(
                        email in self.emails,
                        applicable,
                        f"{email} must{' not' if not applicable else ''} exist",
                    )

    def test_no_physics_teachers_in_primary_school(self):
        for grade in range(1, 5):
            for code in CODES:
                self.assertNotIn(
                    subject_teacher_email(grade, code, PHYSICS_ID), self.emails
                )
        for grade in range(7, 12):
            for code in CODES:
                self.assertIn(
                    subject_teacher_email(grade, code, PHYSICS_ID), self.emails
                )

    def test_informatics_teachers_start_from_grade_four(self):
        for grade in range(1, 4):
            for code in CODES:
                self.assertNotIn(
                    subject_teacher_email(grade, code, INFORMATICS_ID), self.emails
                )
        for grade in range(4, 12):
            for code in CODES:
                self.assertIn(
                    subject_teacher_email(grade, code, INFORMATICS_ID), self.emails
                )

    def test_mathematics_stays_with_the_class_teachers(self):
        for grade in range(1, 12):
            for code in CODES:
                self.assertEqual(
                    subject_teacher_email(grade, code, MATHEMATICS_ID),
                    emails(grade, code),
                )


if __name__ == "__main__":
    unittest.main()
