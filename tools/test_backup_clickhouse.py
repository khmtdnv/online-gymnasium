"""Проверяет безопасный запуск штатного бэкапа ClickHouse."""

import subprocess
import unittest
from unittest.mock import patch

import backup_clickhouse


class BackupClickHouseTests(unittest.TestCase):
    def test_creates_native_backup_with_valid_name(self):
        response = subprocess.CompletedProcess([], 0, stdout="id\tBACKUP_CREATED\n")
        with patch.object(
            backup_clickhouse.subprocess, "run", return_value=response
        ) as run:
            backup_clickhouse.create_backup("demo-20261118")
        command = run.call_args.args[0]
        self.assertIn(
            "BACKUP DATABASE default TO File('backups/demo-20261118.zip')", command
        )
        self.assertTrue(run.call_args.kwargs["check"])

    def test_rejects_unsafe_name_without_running_docker(self):
        with patch.object(backup_clickhouse.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                backup_clickhouse.create_backup("../bad'; DROP DATABASE default")
            run.assert_not_called()

    def test_unexpected_status_is_not_success(self):
        response = subprocess.CompletedProcess([], 0, stdout="id\tBACKUP_FAILED\n")
        with (
            patch.object(backup_clickhouse.subprocess, "run", return_value=response),
            self.assertRaises(RuntimeError),
        ):
            backup_clickhouse.create_backup("demo")


if __name__ == "__main__":
    unittest.main()
