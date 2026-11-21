"""Проверки параметров большого демонстрационного набора."""

import unittest
from datetime import date

from expand_demo_school import (
    CODES,
    LETTERS,
    STUDENTS_PER_CLASS,
    SUBJECTS,
    emails,
    expansion_accounts,
    subject_for,
    subject_teacher_email,
)


class ExpandedSchoolTests(unittest.TestCase):
    def test_unique_accounts_and_existing_demo_addresses(self):
        accounts = expansion_accounts()
        self.assertEqual(len(accounts), 55 * (STUDENTS_PER_CLASS + len(SUBJECTS)))
        self.assertEqual(len({a["email"] for a in accounts}), len(accounts))
        self.assertEqual(emails(1, "a"), "teacher01@demo.og.test")
        self.assertEqual(emails(1, "a", 1), "student01.1@demo.og.test")
        self.assertEqual(len(CODES), len(LETTERS))
        self.assertEqual(
            len(
                {
                    subject_teacher_email(1, "a", subject_id)
                    for subject_id, _ in SUBJECTS
                }
            ),
            len(SUBJECTS),
        )

    def test_age_appropriate_subjects(self):
        monday = date(2026, 11, 16)
        primary = {subject_for(1, monday, slot) for slot in range(4)}
        self.assertNotIn(1006, primary)
        self.assertGreater(len(primary), 1)


if __name__ == "__main__":
    unittest.main()
