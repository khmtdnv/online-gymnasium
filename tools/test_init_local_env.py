"""Первый запуск создаёт согласованные настройки, не меняя существующие."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from init_local_env import initialize

REPO = Path(__file__).resolve().parents[1]


def read(path):
    return dict(
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    )


class InitializeEnvTest(unittest.TestCase):
    def test_partial_setup_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "services" / "gateway"
            directory.mkdir(parents=True)
            shutil.copyfile(
                REPO / "services/gateway/.env.example", directory / ".env.example"
            )
            (directory / ".env").write_text("KEEP=original\n")
            with self.assertRaises(FileExistsError):
                initialize(root)
            self.assertEqual((directory / ".env").read_text(), "KEEP=original\n")

    def test_fresh_settings_match_and_repeat_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for example in (REPO / "services").glob("*/.*.env.example"):
                dest = root / example.relative_to(REPO)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(example, dest)
            for example in (REPO / "services").glob("*/.env.example"):
                dest = root / example.relative_to(REPO)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(example, dest)
            initialize(root)
            gateway = read(root / "services/gateway/.env")
            backoffice = read(root / "services/backoffice/.env")
            journal = read(root / "services/journal/.env")
            billing_worker = read(root / "services/billing/.worker.env")
            self.assertEqual(
                gateway["BACKOFFICE_SERVICE_TOKEN"],
                backoffice["BACKOFFICE_GATEWAY_SERVICE_TOKEN"],
            )
            self.assertEqual(
                journal["BILLING_READ_SERVICE_TOKEN"],
                billing_worker["JOURNAL_SERVICE_TOKEN"],
            )
            self.assertNotEqual(
                journal["BILLING_READ_SERVICE_TOKEN"],
                journal["BACKOFFICE_SERVICE_TOKEN"],
            )
            journal_tokens = [
                journal[key]
                for key in (
                    "BACKOFFICE_SERVICE_TOKEN",
                    "HOMEWORK_SERVICE_TOKEN",
                    "GATEWAY_READ_SERVICE_TOKEN",
                    "BILLING_READ_SERVICE_TOKEN",
                )
            ]
            self.assertEqual(len(journal_tokens), len(set(journal_tokens)))
            self.assertTrue(all(len(token) >= 32 for token in journal_tokens))
            self.assertEqual(
                journal["BACKOFFICE_SERVICE_TOKEN"],
                backoffice["BACKOFFICE_JOURNAL_SERVICE_TOKEN"],
            )
            self.assertEqual(
                journal["GATEWAY_READ_SERVICE_TOKEN"],
                gateway["JOURNAL_READ_SERVICE_TOKEN"],
            )
            homework = read(root / "services/homework/.env")
            schedule = read(root / "services/schedule/.env")
            self.assertEqual(
                homework["JOURNAL_SERVICE_TOKEN"], journal["HOMEWORK_SERVICE_TOKEN"]
            )
            self.assertEqual(
                homework["SCHEDULE_SERVICE_TOKEN"], schedule["HOMEWORK_SERVICE_TOKEN"]
            )
            self.assertEqual(
                homework["MINIO_SECRET_KEY"],
                read(root / "services/homework/.minio.env")["MINIO_SECRET_KEY"],
            )
            self.assertEqual(
                backoffice["BACKOFFICE_DB_PASSWORD"],
                read(root / "services/backoffice/.postgres.env")["POSTGRES_PASSWORD"],
            )
            for service, gateway_key in (
                ("billing", "BILLING_SERVICE_TOKEN"),
                ("documents", "DOCUMENTS_SERVICE_TOKEN"),
                ("notifications", "NOTIFICATIONS_SERVICE_TOKEN"),
                ("pen", "PEN_SERVICE_TOKEN"),
                ("homework", "HOMEWORK_SERVICE_TOKEN"),
                ("schedule", "SCHEDULE_SERVICE_TOKEN"),
            ):
                self.assertEqual(
                    gateway[gateway_key],
                    read(root / f"services/{service}/.env")["GATEWAY_SERVICE_TOKEN"],
                )
            documents = read(root / "services/documents/.env")
            self.assertEqual(
                urlsplit(documents["DOCUMENT_DATABASE_URL"]).password,
                read(root / "services/documents/.postgres.env")["POSTGRES_PASSWORD"],
            )
            self.assertEqual(
                urlsplit(documents["CELERY_BROKER_URL"]).password,
                read(root / "services/documents/.rabbitmq.env")[
                    "RABBITMQ_DEFAULT_PASS"
                ],
            )
            self.assertEqual(
                documents["MINIO_SECRET_KEY"],
                read(root / "services/documents/.minio.env")["MINIO_ROOT_PASSWORD"],
            )
            self.assertEqual(
                (root / "services/gateway/.env").stat().st_mode & 0o777, 0o600
            )
            for service in (
                "gateway",
                "journal",
                "homework",
                "schedule",
                "billing",
                "pen",
                "notifications",
            ):
                env = read(root / f"services/{service}/.env")
                postgres = read(root / f"services/{service}/.postgres.env")
                self.assertEqual(
                    urlsplit(env["DATABASE_URL"]).password,
                    postgres["POSTGRES_PASSWORD"],
                )
            before = (root / "services/gateway/.env").read_text()
            if shutil.which("docker"):
                shutil.copyfile(REPO / "compose.yaml", root / "compose.yaml")
                result = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(root / "compose.yaml"),
                        "config",
                        "--quiet",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            with self.assertRaises(FileExistsError):
                initialize(root)
            self.assertEqual((root / "services/gateway/.env").read_text(), before)


if __name__ == "__main__":
    unittest.main()
