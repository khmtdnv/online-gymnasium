"""Проверяет единый запуск миграций, не подключаясь к базам данных."""

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {
    "schedule": "schedule",
    "document": "documents",
    "gateway": "gateway",
    "journal": "journal",
    "backoffice": "backoffice",
    "homework": "homework",
}


def configuration(overlay=None):
    """Читает итоговую конфигурацию без вывода значений секретов."""
    command = ["docker", "compose", "-f", "compose.yaml"]
    if overlay:
        command += ["-f", overlay]
    command += ["config", "--no-env-resolution", "--format", "json"]
    environment = {**os.environ, "LOCAL_UID": "1234", "LOCAL_GID": "2345"}
    result = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError("Не удалось прочитать Compose; проверьте config --quiet")
    return json.loads(result.stdout)["services"]


class MigrationComposeTests(unittest.TestCase):
    """Проверяет команды, пользователя и границы записи файлов."""

    def test_built_modes_apply_packaged_migrations(self):
        for overlay in (None, "compose.production.yaml"):
            services = configuration(overlay)
            for name in SERVICES:
                with self.subTest(overlay=overlay, service=name):
                    service = services[f"{name}-migrations"]
                    expected = (
                        ["/app/.venv/bin/python", "manage.py", "migrate", "--noinput"]
                        if name == "backoffice"
                        else ["/app/.venv/bin/alembic", "upgrade", "head"]
                    )
                    self.assertEqual(service["command"], expected)
                    self.assertFalse(service.get("volumes"))

    def test_dev_uses_current_sources_and_writable_migrations(self):
        services = configuration("compose.dev.yaml")
        for name, directory in SERVICES.items():
            with self.subTest(service=name):
                service = services[f"{name}-migrations"]
                self.assertEqual(service.get("user"), "1234:2345")
                mounts = {mount["target"]: mount for mount in service["volumes"]}
                source = mounts["/app/src"]
                self.assertEqual(
                    source["source"], str(ROOT / "services" / directory / "src")
                )
                self.assertTrue(source.get("read_only", False))
                target = (
                    "/app/src/backoffice_admin/migrations"
                    if name == "backoffice"
                    else "/app/migrations"
                )
                migrations = mounts[target]
                self.assertFalse(migrations.get("read_only", False))
                relative = (
                    "src/backoffice_admin/migrations"
                    if name == "backoffice"
                    else "migrations"
                )
                self.assertEqual(
                    migrations["source"], str(ROOT / "services" / directory / relative)
                )
                if name == "backoffice":
                    self.assertTrue(mounts["/app/manage.py"].get("read_only", False))
                else:
                    self.assertTrue(mounts["/app/alembic.ini"].get("read_only", False))


if __name__ == "__main__":
    unittest.main()
