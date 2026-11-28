"""Unit tests for the wipe/create modes of tools/balance_demo_lessons_db.py.

Fake session/store/cache in the style of the neighboring tool tests; no
real database is touched.
"""

import hashlib
import importlib.util
import json
import sys
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

_TOOLS_DIR = str(Path(__file__).resolve().parent)
_SCHEDULE_SRC = str(
    Path(__file__).resolve().parents[1] / "services" / "schedule" / "src"
)
for _entry in (_TOOLS_DIR, _SCHEDULE_SRC):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def load_module(name: str):
    """Loads a module from tools without package installation."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


balance = load_module("balance_demo_lessons_db.py")

TEACHER = "11111111-1111-1111-1111-111111111111"
MONDAY = date(2026, 9, 7)
NEXT_MONDAY = date(2026, 9, 14)


def api_path_request_hash(class_id, teacher_id, subject_id, starts_at, ends_at):
    """Independent copy of the hash computation of api/lessons.py."""
    payload = {
        "class_id": class_id,
        "teacher_id": teacher_id,
        "subject_id": subject_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def plan_entry(class_id, day, period, subject_id=1, teacher=TEACHER):
    """One raw entry of a year plan."""
    return {
        "class_id": class_id,
        "subject_id": subject_id,
        "teacher_id": teacher,
        "date": day.isoformat(),
        "period": period,
    }


class FakeDatabase:
    """In-memory lesson/key/event state with snapshot rollback."""

    def __init__(self):
        self.lessons = {}
        self.key_rows = {}
        self.events = []
        self.next_lesson_id = 1
        self.calls = []
        self.tx_log = []

    def snapshot(self):
        return (
            dict(self.lessons),
            {key: dict(row) for key, row in self.key_rows.items()},
            list(self.events),
            self.next_lesson_id,
        )

    def restore(self, state):
        lessons, key_rows, events, next_id = state
        self.lessons = dict(lessons)
        self.key_rows = {key: dict(row) for key, row in key_rows.items()}
        self.events = list(events)
        self.next_lesson_id = next_id

    def seed_lesson(self, class_id, day, period=1, key=None):
        """Adds a lesson row, optionally with its idempotency key."""
        lesson_id = self.next_lesson_id
        self.next_lesson_id += 1
        starts_at, ends_at = balance.lesson_interval(day, period)
        self.lessons[lesson_id] = {
            "id": lesson_id,
            "class_id": class_id,
            "teacher_id": TEACHER,
            "subject_id": 1,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "planned",
            "version": 1,
        }
        if key is not None:
            self.key_rows[key] = {
                "operation": balance.CREATE_LESSON_OPERATION,
                "request_hash": "0" * 64,
                "lesson_id": lesson_id,
            }
        return lesson_id


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

    def __init__(self, db, session=None, fail_on_key=None):
        self.db = db
        self.fail_on_key = fail_on_key

    async def lessons_of_classes(self, class_ids):
        self.db.calls.append(("lessons_of_classes", tuple(sorted(class_ids))))
        wanted = set(class_ids)
        return sorted(
            (row["id"], row["class_id"], row["starts_at"])
            for row in self.db.lessons.values()
            if row["class_id"] in wanted
        )

    async def delete_idempotency_for_lessons(self, lesson_ids):
        self.db.calls.append(
            ("delete_idempotency_for_lessons", tuple(sorted(lesson_ids)))
        )
        wanted = set(lesson_ids)
        doomed = [
            key for key, row in self.db.key_rows.items() if row["lesson_id"] in wanted
        ]
        for key in doomed:
            del self.db.key_rows[key]
        return len(doomed)

    async def delete_lessons(self, lesson_ids):
        self.db.calls.append(("delete_lessons", tuple(sorted(lesson_ids))))
        wanted = set(lesson_ids)
        doomed = [key for key in self.db.lessons if key in wanted]
        for key in doomed:
            del self.db.lessons[key]
        return len(doomed)

    async def existing_keys(self, keys):
        return {key for key in keys if key in self.db.key_rows}

    async def insert_chunk(self, chunk):
        for entry in chunk["entries"]:
            await self.add_lesson(entry)

    async def add_lesson(self, entry):
        if entry["key"] == self.fail_on_key:
            raise RuntimeError("schedule conflict")
        if entry["key"] in self.db.key_rows:
            raise RuntimeError(f"duplicate idempotency key {entry['key']}")
        lesson_id = self.db.next_lesson_id
        self.db.next_lesson_id += 1
        row = {
            "id": lesson_id,
            "class_id": entry["class_id"],
            "teacher_id": entry["teacher_id"],
            "subject_id": entry["subject_id"],
            "starts_at": entry["starts_at"],
            "ends_at": entry["ends_at"],
            "status": "planned",
            "version": 1,
        }
        self.db.lessons[lesson_id] = row
        for event in balance.lesson_events(row):
            self.db.events.append(balance.outbox_row(event))
        self.db.key_rows[entry["key"]] = {
            "operation": balance.CREATE_LESSON_OPERATION,
            "request_hash": entry["request_hash"],
            "lesson_id": lesson_id,
        }


class FakeCache:
    """Day-cache fake proving the wipe committed before it runs."""

    def __init__(self, db):
        self.db = db
        self.deleted = None
        self.lessons_at_delete = None

    async def delete_day_cache(self, class_days):
        self.lessons_at_delete = dict(self.db.lessons)
        self.deleted = sorted(class_days)
        return len(self.deleted)


class ManagedPrefixTests(unittest.TestCase):
    """The managed marker of the export/repair path."""

    def test_all_three_demo_prefixes_are_managed(self):
        self.assertEqual(
            balance.MANAGED_KEY_PREFIXES,
            ("demo-year-%", "demo-expanded-%", "demo-school-%"),
        )

    def test_year_key_format(self):
        self.assertEqual(
            balance.year_idempotency_key(2026, 12, date(2026, 9, 1), 3),
            "demo-year-2026-12-2026-09-01-3",
        )


class RequestHashTests(unittest.TestCase):
    """The request hash must equal the create-lesson API computation."""

    def test_hash_matches_the_api_path(self):
        entry = balance.prepare_entry(plan_entry(12, MONDAY, 3, subject_id=2), 2026)
        start, end = balance.lesson_interval(MONDAY, 3)
        expected = api_path_request_hash(
            12, TEACHER, 2, start.isoformat(), end.isoformat()
        )
        self.assertEqual(entry["request_hash"], expected)

    def test_hash_changes_with_the_body(self):
        first = balance.prepare_entry(plan_entry(1, MONDAY, 1), 2026)
        second = balance.prepare_entry(plan_entry(1, MONDAY, 1, subject_id=2), 2026)
        self.assertNotEqual(first["request_hash"], second["request_hash"])

    def test_period_bounds_come_from_the_school_grid(self):
        start, end = balance.lesson_interval(MONDAY, 3)
        self.assertEqual(start, datetime(2026, 9, 7, 11, 0, tzinfo=start.tzinfo))
        self.assertEqual(end.isoformat(), "2026-09-07T11:45:00+05:00")
        with self.assertRaises(ValueError):
            balance.lesson_interval(MONDAY, 8)


class BuildChunksTests(unittest.TestCase):
    """Class-week chunking of the year plan."""

    def test_chunks_group_and_order_class_weeks(self):
        plan = [
            plan_entry(5, NEXT_MONDAY, 2),
            plan_entry(5, MONDAY, 2),
            plan_entry(5, MONDAY, 1),
            plan_entry(6, MONDAY, 1),
        ]
        chunks = balance.build_chunks(plan, 2026)
        self.assertEqual(
            [(chunk["class_id"], chunk["week_start"]) for chunk in chunks],
            [(5, MONDAY), (5, NEXT_MONDAY), (6, MONDAY)],
        )
        first = chunks[0]
        self.assertEqual([entry["period"] for entry in first["entries"]], [1, 2])
        self.assertEqual(
            first["keys"],
            [
                balance.year_idempotency_key(2026, 5, MONDAY, 1),
                balance.year_idempotency_key(2026, 5, MONDAY, 2),
            ],
        )
        self.assertEqual(
            balance.describe_chunk(first),
            {
                "class_id": 5,
                "week_start": "2026-09-07",
            },
        )

    def test_duplicate_slot_is_rejected(self):
        plan = [plan_entry(5, MONDAY, 1), plan_entry(5, MONDAY, 1, subject_id=2)]
        with self.assertRaises(ValueError):
            balance.build_chunks(plan, 2026)


class WipeTests(unittest.TestCase):
    """The wipe mode of the container run."""

    def setUp(self):
        self.db = FakeDatabase()
        self.cache = FakeCache(self.db)

    def wipe(self, class_ids):
        import asyncio

        return asyncio.run(
            balance.run_wipe(
                lambda session: FakeStore(self.db, session),
                lambda: FakeSession(self.db),
                self.cache,
                class_ids,
            )
        )

    def test_collects_by_class_first_and_deletes_keyless_seeds_too(self):
        managed = self.db.seed_lesson(5, MONDAY, 1, key="demo-school-old")
        seed = self.db.seed_lesson(5, NEXT_MONDAY, 1)  # off-grid fixture seed
        other_class = self.db.seed_lesson(9, MONDAY, 1, key="demo-school-keep")
        result = self.wipe([5])
        self.assertEqual(result["lessons"], 2)
        self.assertEqual(result["idempotency_keys"], 1)
        self.assertEqual(set(self.db.lessons), {other_class})
        self.assertEqual(set(self.db.key_rows), {"demo-school-keep"})
        self.assertNotIn(managed, self.db.lessons)
        self.assertNotIn(seed, self.db.lessons)
        # the fixed order: collect -> keys -> lessons
        self.assertEqual(
            [name for name, _args in self.db.calls],
            [
                "lessons_of_classes",
                "delete_idempotency_for_lessons",
                "delete_lessons",
            ],
        )
        # both collected ids went into the key deletion call
        self.assertEqual(set(self.db.calls[1][1]), {managed, seed})

    def test_drops_day_cache_keys_by_lesson_dates_after_commit(self):
        self.db.seed_lesson(5, MONDAY, 1)
        self.db.seed_lesson(5, MONDAY, 2)  # same class-day: one cache key
        self.db.seed_lesson(5, date(2026, 9, 8), 1)
        self.db.seed_lesson(9, MONDAY, 1)  # another class: not wiped
        result = self.wipe([5])
        self.assertEqual(
            self.cache.deleted,
            [(5, date(2026, 9, 7)), (5, date(2026, 9, 8))],
        )
        self.assertEqual(result["cache_keys"], 2)
        # cache deletion runs after the lesson transaction committed: the
        # wiped class-5 lessons are already gone, only class 9 remains
        remaining = self.cache.lessons_at_delete or {}
        self.assertEqual({row["class_id"] for row in remaining.values()}, {9})
        self.assertEqual(
            balance.day_cache_key(5, MONDAY), "schedule:v2:class:5:date:2026-09-07"
        )

    def test_wipe_of_classes_without_lessons_is_a_noop(self):
        result = self.wipe([5, 6])
        self.assertEqual(result, {"lessons": 0, "idempotency_keys": 0, "cache_keys": 0})


class CreateTests(unittest.TestCase):
    """The create mode of the container run."""

    def setUp(self):
        self.db = FakeDatabase()

    def create(self, plan, study_year=2026, fail_on_key=None):
        import asyncio

        chunks = balance.build_chunks(plan, study_year)
        return asyncio.run(
            balance.run_create(
                lambda session: FakeStore(self.db, session, fail_on_key=fail_on_key),
                lambda: FakeSession(self.db),
                chunks,
            )
        )

    def test_inserts_lessons_events_and_key_rows(self):
        plan = [
            plan_entry(5, MONDAY, 1, subject_id=1),
            plan_entry(5, MONDAY, 3, subject_id=2),
        ]
        result = self.create(plan)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(result["chunks_total"], 1)
        self.assertIsNone(result["failed_chunk"])
        self.assertEqual(result["unfinished_chunks"], [])
        self.assertEqual(self.db.tx_log, ["commit"])
        # lesson rows: version=1, planned, exact period bounds
        rows = sorted(self.db.lessons.values(), key=lambda row: row["id"])
        self.assertEqual([row["version"] for row in rows], [1, 1])
        self.assertEqual([row["status"] for row in rows], ["planned", "planned"])
        self.assertEqual(rows[0]["starts_at"].isoformat(), "2026-09-07T09:00:00+05:00")
        self.assertEqual(rows[1]["ends_at"].isoformat(), "2026-09-07T11:45:00+05:00")
        # key rows: operation and request hash exactly as the API path
        for row, entry in zip(rows, [plan[0], plan[1]], strict=True):
            prepared = balance.prepare_entry(entry, 2026)
            key_row = self.db.key_rows[prepared["key"]]
            self.assertEqual(key_row["operation"], "create_lesson")
            self.assertEqual(key_row["lesson_id"], row["id"])
            self.assertEqual(
                key_row["request_hash"],
                api_path_request_hash(
                    entry["class_id"],
                    TEACHER,
                    entry["subject_id"],
                    row["starts_at"].isoformat(),
                    row["ends_at"].isoformat(),
                ),
            )
        # two events per lesson with the outbox payload format
        self.assertEqual(len(self.db.events), 4)
        changed, snapshot = self.db.events[0], self.db.events[1]
        self.assertEqual(
            changed,
            {
                "event_type": "schedule.changed",
                "payload": {
                    "lesson_id": rows[0]["id"],
                    "class_id": 5,
                    "affected_dates": ["2026-09-07"],
                },
            },
        )
        self.assertEqual(
            snapshot,
            {
                "event_type": "lesson.snapshot",
                "payload": {
                    "lesson_id": rows[0]["id"],
                    "class_id": 5,
                    "teacher_id": TEACHER,
                    "subject_id": 1,
                    "starts_at": "2026-09-07T09:00:00+05:00",
                    "ends_at": "2026-09-07T09:45:00+05:00",
                    "status": "planned",
                    "version": 1,
                },
            },
        )

    def test_rerun_skips_completed_chunks_without_new_rows(self):
        plan = [
            plan_entry(5, MONDAY, 1),
            plan_entry(5, NEXT_MONDAY, 1),
            plan_entry(6, MONDAY, 1),
        ]
        first = self.create(plan)
        self.assertEqual(first["inserted"], 3)
        lessons_after_first = dict(self.db.lessons)
        events_after_first = list(self.db.events)
        second = self.create(plan)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["chunks_skipped"], 3)
        self.assertIsNone(second["failed_chunk"])
        self.assertEqual(self.db.lessons, lessons_after_first)
        self.assertEqual(self.db.events, events_after_first)

    def test_failed_chunk_rolls_back_completely_and_neighbors_survive(self):
        plan = [
            plan_entry(5, MONDAY, 1),  # chunk one: class 5, first week
            plan_entry(5, NEXT_MONDAY, 1),  # chunk two: class 5, next week
            plan_entry(5, NEXT_MONDAY, 2),  # fails here, second entry
            plan_entry(6, MONDAY, 1),  # chunk three: never attempted
        ]
        failing_key = balance.year_idempotency_key(2026, 5, NEXT_MONDAY, 2)
        result = self.create(plan, fail_on_key=failing_key)
        self.assertIn("schedule conflict", result["failed_chunk"]["error"])
        self.assertEqual(result["failed_chunk"]["class_id"], 5)
        self.assertEqual(result["failed_chunk"]["week_start"], "2026-09-14")
        # the first chunk committed, the failed one rolled back whole
        # (its first entry vanished with it), the last one was not attempted
        self.assertEqual(self.db.tx_log, ["commit", "rollback"])
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(
            result["unfinished_chunks"],
            [
                {"class_id": 5, "week_start": "2026-09-14"},
                {"class_id": 6, "week_start": "2026-09-07"},
            ],
        )
        self.assertEqual(set(self.db.lessons), {1})
        self.assertEqual(
            set(self.db.key_rows),
            {balance.year_idempotency_key(2026, 5, MONDAY, 1)},
        )

    def test_partially_present_chunk_fails_and_rolls_back(self):
        plan = [plan_entry(5, MONDAY, 1), plan_entry(5, MONDAY, 2)]
        debris = balance.prepare_entry(plan_entry(5, MONDAY, 1), 2026)
        self.db.key_rows[debris["key"]] = {
            "operation": balance.CREATE_LESSON_OPERATION,
            "request_hash": debris["request_hash"],
            "lesson_id": None,
        }
        result = self.create(plan)
        self.assertIsNotNone(result["failed_chunk"])
        self.assertEqual(self.db.tx_log, ["rollback"])
        self.assertEqual(len(self.db.lessons), 0)


class HelperTests(unittest.TestCase):
    """Small pure helpers."""

    def test_in_batches_preserves_order_and_size(self):
        batches = list(balance.in_batches(list(range(2501)), size=1000))
        self.assertEqual([len(batch) for batch in batches], [1000, 1000, 501])
        self.assertEqual(
            [item for batch in batches for item in batch], list(range(2501))
        )

    def test_outbox_row_rejects_unknown_events(self):
        with self.assertRaises(TypeError):
            balance.outbox_row(object())


class DiaryExportTests(unittest.TestCase):
    """Чистые помошники расширенного export-режима дневника."""

    def test_diary_window_is_study_year_start_to_today(self):
        from schedule_service.domain import school_calendar

        today = date(2026, 11, 16)
        self.assertEqual(
            balance.diary_window(today),
            (school_calendar.STUDY_YEAR[0], today),
        )
        with self.assertRaises(ValueError):
            balance.diary_window(date(2026, 8, 31))

    def test_lesson_school_date_derives_from_starts_at(self):
        # 04:00 UTC = 09:00 школьного пояса того же дня.
        morning = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)
        self.assertEqual(balance.lesson_school_date(morning), date(2026, 11, 16))
        # 22:00 UTC = 03:00 следующего школьного дня.
        late = datetime(2026, 11, 16, 22, 0, tzinfo=UTC)
        self.assertEqual(balance.lesson_school_date(late), date(2026, 11, 17))

    def test_serialize_diary_carries_status_and_school_date(self):
        row = SimpleNamespace(
            id=501,
            class_id=7,
            subject_id=3,
            teacher_id=UUID(TEACHER),
            starts_at=datetime(2026, 11, 16, 4, 0, tzinfo=UTC),
            ends_at=datetime(2026, 11, 16, 4, 45, tzinfo=UTC),
            status="planned",
        )
        self.assertEqual(
            balance.serialize_diary(row),
            {
                "lesson_id": 501,
                "class_id": 7,
                "subject_id": 3,
                "teacher_id": TEACHER,
                "starts_at": "2026-11-16T04:00:00+00:00",
                "ends_at": "2026-11-16T04:45:00+00:00",
                "status": "planned",
                "date": "2026-11-16",
            },
        )

    def test_diary_export_rows_keep_managed_and_chronological(self):
        def row(lesson_id, hour, status="planned"):
            return SimpleNamespace(
                id=lesson_id,
                class_id=7,
                subject_id=3,
                teacher_id=UUID(TEACHER),
                starts_at=datetime(2026, 11, 16, hour, 0, tzinfo=UTC),
                ends_at=datetime(2026, 11, 16, hour, 45, tzinfo=UTC),
                status=status,
            )

        rows = [row(2, 5), row(1, 4, "canceled"), row(3, 6)]
        result = balance.diary_export_rows(rows, {1, 3})
        self.assertEqual(
            [item["lesson_id"] for item in result],
            [1, 3],
        )
        # Статусы сохраняются: пропуск отменённых — задача генератора.
        self.assertEqual(result[0]["status"], "canceled")
        self.assertEqual(result[1]["status"], "planned")
        unmanaged = balance.diary_export_rows(rows, {2})
        self.assertEqual([item["lesson_id"] for item in unmanaged], [2])


if __name__ == "__main__":
    unittest.main()
