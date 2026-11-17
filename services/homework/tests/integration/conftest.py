"""Тесты БД разрешены только для явно выбранной одноразовой базы."""

import asyncio
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from homework_service.config import HomeworkSettings


@pytest.fixture
def minio_settings():
    """Разрешает объектные проверки только в отдельном локальном test bucket."""
    endpoint = os.getenv("HOMEWORK_TEST_MINIO_ENDPOINT")
    if not endpoint:
        pytest.skip("Set HOMEWORK_TEST_MINIO_* to an isolated local test storage")
    parsed = urlsplit(f"http://{endpoint}")
    bucket = os.environ["HOMEWORK_TEST_MINIO_BUCKET"]
    assert parsed.hostname in ("127.0.0.1", "localhost") and bucket.startswith(
        "homework-test-"
    )
    return HomeworkSettings(
        database_url="unused",
        _env_file=None,
        minio_endpoint=endpoint,
        minio_bucket=bucket,
        minio_access_key=os.environ["HOMEWORK_TEST_MINIO_ACCESS_KEY"],
        minio_secret_key=os.environ["HOMEWORK_TEST_MINIO_SECRET_KEY"],
    )


@pytest.fixture(scope="session")
def database_url():
    url = os.getenv("HOMEWORK_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set HOMEWORK_TEST_DATABASE_URL to a disposable homework_test_* database"
        )
    if not (make_url(url).database or "").startswith("homework_test_"):
        pytest.fail("Refusing to migrate a database outside homework_test_*")
    return url


@pytest.fixture(scope="session")
def migrate(database_url):
    root = Path(__file__).resolve().parents[2]

    def run(revision, direction="upgrade"):
        result = subprocess.run(
            [str(root / ".venv/bin/alembic"), direction, revision],
            cwd=root,
            env={**os.environ, "DATABASE_URL": database_url},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    run("head")
    return run


@pytest.fixture
def engine(database_url, migrate):
    engine = create_async_engine(database_url, poolclass=NullPool)

    async def clear():
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE homework_event_outbox, homework_answer_files, homework_answers, homework_files, homework_assignments RESTART IDENTITY"
                )
            )

    asyncio.run(clear())
    yield engine
    asyncio.run(engine.dispose())
