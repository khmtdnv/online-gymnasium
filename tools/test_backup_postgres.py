"""Проверяет безопасное создание отдельных архивов PostgreSQL."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_postgres


class BackupPostgresTests(unittest.TestCase):
    def test_creates_nine_private_archives_and_completion_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup"

            def run(command, *, stdout, check, cwd):
                self.assertTrue(check)
                self.assertIn("pg_dump", command[-1])
                stdout.write(b"PGDMP-test")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(backup_postgres.subprocess, "run", side_effect=run):
                backup_postgres.create_backup(target)

            self.assertEqual(len(list(target.glob("*.dump"))), 9)
            self.assertTrue((target / "COMPLETE").is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertTrue(
                all(p.stat().st_mode & 0o777 == 0o600 for p in target.glob("*.dump"))
            )

    def test_does_not_overwrite_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup"
            target.mkdir()
            (target / "keep").write_text("original")
            with self.assertRaises(FileExistsError):
                backup_postgres.create_backup(target)
            self.assertEqual((target / "keep").read_text(), "original")

    def test_failure_does_not_mark_backup_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup"
            with (
                patch.object(
                    backup_postgres.subprocess,
                    "run",
                    side_effect=subprocess.CalledProcessError(1, "docker"),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                backup_postgres.create_backup(target)
            self.assertFalse((target / "COMPLETE").exists())

    def test_empty_dump_does_not_mark_backup_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup"
            with (
                patch.object(backup_postgres.subprocess, "run", return_value=None),
                self.assertRaises(ValueError),
            ):
                backup_postgres.create_backup(target)
            self.assertFalse((target / "COMPLETE").exists())


if __name__ == "__main__":
    unittest.main()
