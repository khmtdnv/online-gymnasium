"""Unit tests for tools/reset_demo_passwords.py.

Fake store/session/password service in the style of the neighboring
tool tests; no real database is touched.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from uuid import uuid4

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


reset = load_module("reset_demo_passwords.py")

TEACHER = uuid4()
STUDENT = uuid4()
PARENT = uuid4()
ADMIN = uuid4()


class FakeDatabase:
    """In-memory users with refresh tokens and sessions."""

    def __init__(self):
        self.users = {}
        self.tx_log = []

    def seed_user(self, user_id, email, role, *, tokens=0, sessions=0):
        self.users[user_id] = {
            "email": email,
            "role": role,
            "password_hash": f"old-hash-{email}",
            "refresh_tokens": [f"token-{email}-{i}" for i in range(tokens)],
            "sessions": [
                {"revoked_at": None} if i < sessions else {"revoked_at": "past"}
                for i in range(sessions)
            ],
        }

    def snapshot(self):
        return {key: dict(value) for key, value in self.users.items()}

    def restore(self, state):
        self.users = {key: dict(value) for key, value in state.items()}


class FakeSession:
    """Async session whose begin() snapshots and rolls back on errors."""

    def __init__(self, db):
        self.db = db

    def begin(self):
        return FakeTransaction(self.db)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeTransaction:
    """Commits on clean exit, restores the snapshot on any exception."""

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

    async def find_users(self, emails):
        return [
            {"id": user_id, "email": user["email"], "role": user["role"]}
            for user_id, user in self.db.users.items()
            if user["email"] in emails
        ]

    async def update_password(self, user_id, password_hash):
        self.db.users[user_id]["password_hash"] = password_hash

    async def delete_refresh_tokens(self, user_id):
        tokens = self.db.users[user_id]["refresh_tokens"]
        count = len(tokens)
        tokens.clear()
        return count

    async def revoke_sessions(self, user_id):
        sessions = self.db.users[user_id]["sessions"]
        count = 0
        for session in sessions:
            if session["revoked_at"] is None:
                session["revoked_at"] = "now"
                count += 1
        return count


def store_of(db):
    """Store factory binding the fake database regardless of session."""
    return lambda session: FakeStore(db)


class FakePasswordService:
    """Hashes deterministically; can break verify for the self-check test."""

    def __init__(self, *, broken_verify=False):
        self.broken_verify = broken_verify

    def hash(self, plain_password):
        return f"hash-of:{plain_password}"

    def verify(self, plain_password, password_hash):
        return not self.broken_verify and password_hash == f"hash-of:{plain_password}"


class SessionFactory:
    """Yields one FakeSession per call."""

    def __init__(self, db):
        self.db = db

    def __call__(self):
        return FakeSession(self.db)


class ParseEmailsTest(unittest.TestCase):
    def test_accepts_demo_emails_and_drops_duplicates(self):
        self.assertEqual(
            reset.parse_emails(["teacher01@demo.og.test", "teacher01@demo.og.test"]),
            ["teacher01@demo.og.test"],
        )

    def test_rejects_non_demo_domain(self):
        with self.assertRaises(SystemExit):
            reset.parse_emails(["teacher01@school.ru"])

    def test_rejects_empty_or_non_list(self):
        with self.assertRaises(SystemExit):
            reset.parse_emails([])
        with self.assertRaises(SystemExit):
            reset.parse_emails("teacher01@demo.og.test")

    def test_password_must_be_non_blank(self):
        self.assertEqual(reset.parse_password("DemoSchool2026!"), "DemoSchool2026!")
        with self.assertRaises(SystemExit):
            reset.parse_password("   ")
        with self.assertRaises(SystemExit):
            reset.parse_password(None)


class RunResetTest(unittest.TestCase):
    def _db(self):
        db = FakeDatabase()
        db.seed_user(TEACHER, "teacher01@demo.og.test", "teacher", tokens=2, sessions=1)
        db.seed_user(
            STUDENT, "student01.1@demo.og.test", "student", tokens=1, sessions=0
        )
        db.seed_user(PARENT, "parent01@demo.og.test", "parent", tokens=0, sessions=2)
        db.seed_user(ADMIN, "admin@demo.og.test", "admin")
        return db

    def _run(self, db, emails, service=None):
        return asyncio_run(
            reset.run_reset(
                store_of(db),
                service or FakePasswordService(),
                SessionFactory(db),
                emails,
                "DemoSchool2026!",
            )
        )

    def test_changes_hashes_and_revokes_old_credentials(self):
        db = self._db()
        result = self._run(
            db,
            [
                "teacher01@demo.og.test",
                "student01.1@demo.og.test",
                "parent01@demo.og.test",
            ],
        )
        self.assertEqual(db.tx_log, ["commit"])
        for user_id in (TEACHER, STUDENT, PARENT):
            self.assertEqual(
                db.users[user_id]["password_hash"], "hash-of:DemoSchool2026!"
            )
            self.assertEqual(db.users[user_id]["refresh_tokens"], [])
        self.assertEqual(
            db.users[ADMIN]["password_hash"], "old-hash-admin@demo.og.test"
        )
        self.assertEqual(result["missing"], [])
        by_email = {row["email"]: row for row in result["changed"]}
        self.assertEqual(
            by_email["teacher01@demo.og.test"]["refresh_tokens_deleted"], 2
        )
        self.assertEqual(by_email["parent01@demo.og.test"]["sessions_revoked"], 2)
        self.assertEqual(by_email["student01.1@demo.og.test"]["sessions_revoked"], 0)

    def test_reports_missing_emails_without_touching_them(self):
        db = self._db()
        result = self._run(db, ["teacher01@demo.og.test", "teacher99@demo.og.test"])
        self.assertEqual(result["missing"], ["teacher99@demo.og.test"])
        self.assertEqual(db.users[TEACHER]["password_hash"], "hash-of:DemoSchool2026!")

    def test_admin_is_refused_and_transaction_rolls_back(self):
        db = self._db()
        with self.assertRaises(SystemExit):
            self._run(db, ["teacher01@demo.og.test", "admin@demo.og.test"])
        self.assertEqual(db.tx_log, ["rollback"])
        for user in db.users.values():
            self.assertTrue(user["password_hash"].startswith("old-hash-"))
            self.assertNotEqual(user["password_hash"], "hash-of:DemoSchool2026!")

    def test_broken_hash_self_check_rolls_back(self):
        db = self._db()
        with self.assertRaises(SystemExit):
            self._run(
                db,
                ["teacher01@demo.og.test"],
                service=FakePasswordService(broken_verify=True),
            )
        self.assertEqual(db.tx_log, ["rollback"])
        self.assertEqual(
            db.users[TEACHER]["password_hash"], "old-hash-teacher01@demo.og.test"
        )


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


if __name__ == "__main__":
    unittest.main()
