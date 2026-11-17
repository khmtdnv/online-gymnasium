"""Настоящие HTTP-приложения трёх сервисов с одноразовой PG Journal."""

import asyncio
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn
from conftest import database

from journal_service.app import create_app
from journal_service.config import JournalSettings
from journal_service.domain.school_class import Class
from journal_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from journal_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


@contextmanager
def server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    instance = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    thread = threading.Thread(target=lambda: instance.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not instance.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test server did not start")
            time.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        instance.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_backoffice_journal_gateway_roundtrip(database_url):
    root = Path(__file__).resolve().parents[3]
    teacher = uuid4()

    async def prepare():
        async with database(database_url) as (_, factory), factory() as uow:
            return (await uow.classes.create_class(Class("7А", 2026))).id

    class_id = asyncio.run(prepare())
    # Gateway работает в собственном окружении. Его хранилище пользователей
    # тестовое in-memory; настоящие router/handler/auth/serialization сохраняются.
    gateway_script = """
import os,sys
from uuid import UUID
from pathlib import Path
import uvicorn
sys.path.insert(0,str(Path('tests').resolve()))
from test_internal_users_api import make_app
from gateway_service.domain.user import User,Role
user=User(UUID(os.environ['TEACHER_TEST_ID']),'teacher@example.test',Role.TEACHER,'test-hash',True,first_name='Иван',last_name='Петров')
app,_=make_app(user,secret='teacher-test-reader-token')
uvicorn.run(app,host='127.0.0.1',port=int(os.environ['TEACHER_TEST_GATEWAY_PORT']),log_level='error')
"""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env = dict(
        os.environ, TEACHER_TEST_ID=str(teacher), TEACHER_TEST_GATEWAY_PORT=str(port)
    )
    gateway = subprocess.Popen(
        ["poetry", "-C", str(root / "gateway"), "run", "python", "-c", gateway_script],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    engine = None
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                with httpx.Client(timeout=0.5) as check:
                    response = check.get(
                        f"http://127.0.0.1:{port}/internal/users/{teacher}",
                        headers={"Authorization": "Bearer teacher-test-reader-token"},
                    )
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if gateway.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Gateway test server did not start")
            time.sleep(0.05)
        # Engine используется в loop Journal-сервера, а не loop подготовки данных.
        engine = create_engine(database_url)
        sessions = create_session_factory(engine)
        app = create_app(
            JournalSettings(
                database_url=database_url,
                backoffice_service_token="teacher-test-backoffice-token",
                gateway_base_url=f"http://127.0.0.1:{port}",
                gateway_service_token="teacher-test-reader-token",
                _env_file=None,
            ),
            lambda: SqlAlchemyUnitOfWork(sessions),
            close_resources=engine.dispose,
        )
        with server(app) as journal_url:
            env.update(
                TEACHER_TEST_JOURNAL_URL=journal_url, TEACHER_TEST_CLASS=str(class_id)
            )
            result = subprocess.run(
                [
                    "poetry",
                    "-C",
                    str(root / "backoffice"),
                    "run",
                    "python",
                    "tests/helpers/teacher_class_http_flow.py",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert result.returncode == 0, (
                "Backoffice HTTP flow failed: "
                + result.stdout[-500:]
                + result.stderr[-1500:]
            )
    finally:
        gateway.terminate()
        try:
            gateway.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gateway.kill()
            gateway.wait()
