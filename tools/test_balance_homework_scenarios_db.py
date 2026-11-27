"""Unit tests for tools/balance_homework_scenarios_db.py.

Fake session/store in the style of the neighboring tool tests; no real
database is touched.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from uuid import UUID

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)


def load_module(name: str):
    """Loads a module from tools without package installation."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


homework = load_module("balance_homework_scenarios_db.py")

DEMO_TEACHER = UUID("11111111-1111-1111-1111-111111111111")
OUTSIDE_TEACHER = UUID("22222222-2222-2222-2222-222222222222")
DEMO_CLASS = 5
OUTSIDE_CLASS = 9


class FakeDatabase:
    """In-memory homework state with snapshot rollback."""

    def __init__(self):
        self.assignments = {}  # id -> {"author_id", "class_id"}
        self.answers = {}  # id -> homework_id
        self.answer_files = {}  # id -> answer_id
        self.files = {}  # id -> homework_id
        self.next_id = 1
        self.calls = []
        self.tx_log = []

    def snapshot(self):
        return (
            dict(self.assignments),
            dict(self.answers),
            dict(self.answer_files),
            dict(self.files),
            self.next_id,
        )

    def restore(self, state):
        (
            self.assignments,
            self.answers,
            self.answer_files,
            self.files,
            self.next_id,
        ) = state

    def seed_assignment(self, author_id, class_id, *, answers=0, files=0):
        """Adds an assignment with answers, answer files and attachments."""
        homework_id = self.next_id
        self.next_id += 1
        self.assignments[homework_id] = {"author_id": author_id, "class_id": class_id}
        for _ in range(answers):
            answer_id = self.next_id
            self.next_id += 1
            self.answers[answer_id] = homework_id
            self.answer_files[answer_id] = answer_id  # one file per answer
        for _ in range(files):
            file_id = self.next_id
            self.next_id += 1
            self.files[file_id] = homework_id
        return homework_id


class FakeSession:
    """Async session with real-transaction semantics over FakeDatabase."""

    def __init__(self, db):
        self.db = db

    def begin(self):
        return FakeTransaction(self.db)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeTransaction:
    """Commits on clean exit, restores the snapshot on an error."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self._state = self.db.snapshot()
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is not None:
            self.db.tx_log.append("rollback")
            self.db.restore(self._state)
        else:
            self.db.tx_log.append("commit")
        return False


class FakeStore:
    """The store interface of the tool over FakeDatabase."""

    def __init__(self, db, session=None):
        self.db = db

    async def demo_homework_ids(self, teacher_ids, class_ids):
        self.db.calls.append(("demo_homework_ids", tuple(sorted(class_ids))))
        teachers = set(teacher_ids)
        classes = set(class_ids)
        return sorted(
            homework_id
            for homework_id, row in self.db.assignments.items()
            if row["author_id"] in teachers and row["class_id"] in classes
        )

    async def delete_answer_files(self, homework_ids):
        self.db.calls.append(("delete_answer_files", tuple(sorted(homework_ids))))
        wanted = set(homework_ids)
        answer_ids = {
            answer_id for answer_id, owner in self.db.answers.items() if owner in wanted
        }
        doomed = [
            file_id
            for file_id, answer_id in self.db.answer_files.items()
            if answer_id in answer_ids
        ]
        for file_id in doomed:
            del self.db.answer_files[file_id]
        return len(doomed)

    async def delete_answers(self, homework_ids):
        self.db.calls.append(("delete_answers", tuple(sorted(homework_ids))))
        wanted = set(homework_ids)
        doomed = [
            answer_id for answer_id, owner in self.db.answers.items() if owner in wanted
        ]
        for answer_id in doomed:
            del self.db.answers[answer_id]
        return len(doomed)

    async def delete_files(self, homework_ids):
        self.db.calls.append(("delete_files", tuple(sorted(homework_ids))))
        wanted = set(homework_ids)
        doomed = [
            file_id for file_id, owner in self.db.files.items() if owner in wanted
        ]
        for file_id in doomed:
            del self.db.files[file_id]
        return len(doomed)

    async def delete_assignments(self, homework_ids):
        self.db.calls.append(("delete_assignments", tuple(sorted(homework_ids))))
        wanted = set(homework_ids)
        doomed = [
            homework_id for homework_id in self.db.assignments if homework_id in wanted
        ]
        for homework_id in doomed:
            del self.db.assignments[homework_id]
        return len(doomed)


class HomeworkWipeTests(unittest.TestCase):
    """The demo-scenario wipe of the homework container run."""

    def setUp(self):
        self.db = FakeDatabase()

    def wipe(self, teacher_ids=(DEMO_TEACHER,), class_ids=(DEMO_CLASS,)):
        import asyncio

        return asyncio.run(
            homework.run_wipe(
                lambda session: FakeStore(self.db, session),
                lambda: FakeSession(self.db),
                list(teacher_ids),
                list(class_ids),
            )
        )

    def test_selects_only_demo_teacher_and_demo_class_rows(self):
        inside = self.db.seed_assignment(DEMO_TEACHER, DEMO_CLASS, answers=2, files=1)
        wrong_class = self.db.seed_assignment(DEMO_TEACHER, OUTSIDE_CLASS)
        wrong_teacher = self.db.seed_assignment(OUTSIDE_TEACHER, DEMO_CLASS)
        outside = self.db.seed_assignment(OUTSIDE_TEACHER, OUTSIDE_CLASS)
        result = self.wipe()
        self.assertEqual(result["assignments"], 1)
        self.assertEqual(result["answers"], 2)
        self.assertEqual(result["answer_files"], 2)
        self.assertEqual(result["files"], 1)
        self.assertNotIn(inside, self.db.assignments)
        self.assertEqual(
            set(self.db.assignments), {wrong_class, wrong_teacher, outside}
        )
        self.assertEqual(self.db.tx_log, ["commit"])

    def test_answers_and_file_links_follow_their_assignments(self):
        demo = self.db.seed_assignment(DEMO_TEACHER, DEMO_CLASS, answers=3, files=2)
        other = self.db.seed_assignment(
            OUTSIDE_TEACHER, OUTSIDE_CLASS, answers=1, files=1
        )
        self.wipe([DEMO_TEACHER], [DEMO_CLASS, OUTSIDE_CLASS])
        self.assertNotIn(demo, self.db.assignments)
        self.assertEqual(set(self.db.answers), {8})  # the outside answer remains
        self.assertEqual(set(self.db.answer_files), {8})
        self.assertEqual(set(self.db.files), {9})  # the outside file remains
        self.assertIn(other, self.db.assignments)

    def test_children_are_deleted_before_assignments(self):
        self.db.seed_assignment(DEMO_TEACHER, DEMO_CLASS, answers=1, files=1)
        self.wipe()
        self.assertEqual(
            [name for name, _args in self.db.calls],
            [
                "demo_homework_ids",
                "delete_answer_files",
                "delete_answers",
                "delete_files",
                "delete_assignments",
            ],
        )

    def test_rerun_is_an_empty_result(self):
        self.db.seed_assignment(DEMO_TEACHER, DEMO_CLASS, answers=1, files=1)
        first = self.wipe()
        self.assertEqual(first["assignments"], 1)
        snapshot = self.db.snapshot()
        second = self.wipe()
        self.assertEqual(
            second,
            {"assignments": 0, "answers": 0, "answer_files": 0, "files": 0},
        )
        self.assertEqual(self.db.snapshot(), snapshot)

    def test_empty_input_deletes_nothing(self):
        self.db.seed_assignment(DEMO_TEACHER, DEMO_CLASS, answers=1)
        result = self.wipe(teacher_ids=[], class_ids=[])
        self.assertEqual(result["assignments"], 0)
        self.assertEqual(len(self.db.assignments), 1)

    def test_input_parsers_validate_ids(self):
        self.assertEqual(homework.parse_teachers([str(DEMO_TEACHER)]), [DEMO_TEACHER])
        self.assertEqual(homework.parse_classes(["5", 6]), [5, 6])
        with self.assertRaises(ValueError):
            homework.parse_teachers(["not-a-uuid"])


if __name__ == "__main__":
    unittest.main()
