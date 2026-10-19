"""Тесты БД разрешены только для явно выбранной одноразовой базы."""

import asyncio
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


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
                text("TRUNCATE homework_assignments RESTART IDENTITY")
            )

    asyncio.run(clear())
    yield engine
    asyncio.run(engine.dispose())
