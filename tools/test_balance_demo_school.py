"""Ключевые свойства распределения демонстрационного расписания."""

import unittest

from balance_demo_school import plan_teacher_load


def lesson(id, class_id, teacher, start, version=1, managed=True):
    return {
        "id": id,
        "class_id": class_id,
        "teacher_id": teacher,
        "subject_id": 1,
        "starts_at": f"2026-11-{start[0]}T{start[1]}:00:00+05:00",
        "ends_at": f"2026-11-{start[0]}T{start[1]}:45:00+05:00",
        "version": version,
        "managed": managed,
    }


class TeacherBalanceTests(unittest.TestCase):
    def test_same_teacher_for_class_and_no_overlapping_classes(self):
        rows = [
            lesson(1, 1, "old1", ("16", "09")),
            lesson(2, 1, "old1", ("17", "10")),
            lesson(3, 2, "old2", ("16", "10")),
            lesson(4, 2, "old2", ("17", "11")),
            lesson(5, 3, "old3", ("16", "09")),
        ]
        expected = {(1, 1): {"old1"}, (2, 1): {"old2"}, (3, 1): {"old3"}}
        plan = plan_teacher_load(rows, {1: ["teacher1", "teacher2"]}, expected)
        assigned = {row["id"]: row["teacher_id"] for row in plan}
        self.assertEqual(assigned[1], assigned[2])
        self.assertEqual(assigned[3], assigned[4])
        self.assertEqual(assigned[1], assigned[3])
        self.assertNotEqual(assigned[1], assigned[5])

    def test_unmanaged_lessons_are_not_changed_and_reserve_time(self):
        rows = [
            lesson(1, 1, "old1", ("16", "09")),
            lesson(2, 99, "teacher1", ("16", "09"), managed=False),
        ]
        plan = plan_teacher_load(
            rows, {1: ["teacher1", "teacher2"]}, {(1, 1): {"old1"}}
        )
        self.assertEqual([(x["id"], x["teacher_id"]) for x in plan], [(1, "teacher2")])


if __name__ == "__main__":
    unittest.main()
