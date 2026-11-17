"""Один сквозной цикл JWT→Gateway→Homework→PostgreSQL с актуальными правами."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from gateway_service.app import create_app
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.token_service import PyJwtTokenService


def test_submit_return_resubmit_grade_and_current_permissions(monkeypatch):
    url = os.getenv("HOMEWORK_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set HOMEWORK_TEST_DATABASE_URL to an already migrated disposable DB"
        )
    assert (make_url(url).database or "").startswith("homework_test_")
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "homework" / "src")
    )
    from homework_service.app import create_app as create_homework
    from homework_service.application.homework_answers import (
        ReadHomeworkAnswersHandler,
        ReviewHomeworkAnswerHandler,
        SubmitHomeworkAnswerHandler,
    )
    from homework_service.application.ports.schedule_reader import LessonInfo
    from homework_service.config import HomeworkSettings
    from homework_service.domain.homework import Homework
    from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

    student = User(
        UUID(int=1),
        "student@example.test",
        Role.STUDENT,
        "hash",
        True,
        "Иван",
        "Петров",
    )
    teacher = User(
        UUID(int=2),
        "teacher@example.test",
        Role.TEACHER,
        "hash",
        True,
        "Анна",
        "Иванова",
    )
    stranger = User(
        UUID(int=3),
        "other@example.test",
        Role.STUDENT,
        "hash",
        True,
        "Максим",
        "Петров",
    )
    users = {user.id: user for user in (student, teacher, stranger)}
    names_calls = []

    async def get_user(user_id):
        return users.get(user_id)

    async def get_users(ids):
        names_calls.append(ids)
        return [users[id] for id in ids if id in users]

    @asynccontextmanager
    async def gateway_uow():
        yield SimpleNamespace(
            users=SimpleNamespace(get_by_id=get_user, get_by_ids=get_users)
        )

    state = {"class_id": 7, "assigned": True}

    async def current_class(user_id):
        return state["class_id"]

    async def assigned(user_id, class_id):
        return state["assigned"]

    now = datetime.now(UTC)

    async def lessons(ids):
        return {
            id: LessonInfo(
                id=id,
                class_id=7,
                subject_id=3,
                teacher_id=teacher.id,
                starts_at=now,
                ends_at=now + timedelta(hours=1),
                status="planned",
                version=1,
            )
            for id in ids
        }

    async def run():
        engine = create_async_engine(url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        def uow():
            return SqlAlchemyUnitOfWork(sessions)

        async with uow() as unit:
            # Урок1 из fixture уже существует: отдельный ID не меняет старые данные.
            parent = await unit.homeworks.add(
                Homework(
                    issued_lesson_id=1938476,
                    class_id=7,
                    subject_id=3,
                    author_id=teacher.id,
                    description="Решить",
                    manual_due_datetime=now - timedelta(days=1),
                )
            )
        deps = (
            uow,
            SimpleNamespace(
                get_current_class_id=current_class, is_teacher_assigned=assigned
            ),
            SimpleNamespace(get_lessons=lessons),
        )
        source = create_homework(
            HomeworkSettings(
                database_url="unused", gateway_service_token="gw", _env_file=None
            ),
            AsyncMock(),
            submit_homework_answer_handler=SubmitHomeworkAnswerHandler(*deps),
            review_homework_answer_handler=ReviewHomeworkAnswerHandler(*deps),
            read_homework_answers_handler=ReadHomeworkAnswersHandler(*deps),
        )
        settings = GatewaySettings(
            database_url="unused",
            jwt_secret="test-only-secret-which-is-at-least-32-bytes",
            backoffice_service_token="bo",
            _env_file=None,
        )
        tokens = PyJwtTokenService(settings)
        headers = lambda user: {
            "Authorization": f"Bearer {tokens.issue_access(user)}",
            "X-User-ID": str(teacher.id),
            "X-User-Role": "teacher",
        }
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=source), base_url="http://homework"
            ) as internal:
                private_path = f"/internal/homework/{parent.id}/answers"
                assert (
                    await internal.post(
                        private_path,
                        headers={
                            "X-User-ID": str(student.id),
                            "X-User-Role": "student",
                            "Idempotency-Key": "bad-auth",
                        },
                        json={"answer_text": "Ответ"},
                    )
                ).status_code == 401
                assert (
                    await internal.post(
                        private_path,
                        headers={
                            "Authorization": "Bearer gw",
                            "X-User-ID": str(student.id),
                            "X-User-Role": "student",
                            "Idempotency-Key": "bad-body",
                        },
                        json={"answer_text": "Ответ", "student_id": str(stranger.id)},
                    )
                ).status_code == 422
                gateway = create_app(
                    settings,
                    AsyncMock(),
                    gateway_uow,
                    Mock(),
                    tokens,
                    homework_client=HomeworkClient(internal, "gw"),
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=gateway),
                    base_url="http://gateway",
                ) as public:
                    path = f"/api/v1/homework/{parent.id}/answers"
                    body = {"answer_text": "Первый ответ", "files": []}
                    response = await public.post(
                        path,
                        headers={**headers(student), "Idempotency-Key": "first"},
                        json=body,
                    )
                    assert response.status_code == 201, response.text
                    assert response.headers["Cache-Control"] == "private, no-store"
                    answer = response.json()
                    assert answer["student_id"] == str(student.id)
                    assert answer["student_name"] == "Петров Иван"
                    assert not {"idempotency_key", "request_hash"}.intersection(answer)
                    replay = await public.post(
                        path,
                        headers={**headers(student), "Idempotency-Key": "first"},
                        json=body,
                    )
                    assert (
                        replay.status_code == 200
                        and replay.json()["id"] == answer["id"]
                    )
                    assert (
                        await public.get(
                            f"{path}/{answer['id']}", headers=headers(stranger)
                        )
                    ).status_code == 404
                    assert (
                        await public.get(
                            path,
                            headers=headers(student),
                            params={"student_id": str(stranger.id)},
                        )
                    ).status_code == 403
                    review_path = f"{path}/{answer['id']}/review"
                    assert (
                        await public.put(
                            review_path,
                            headers=headers(student),
                            json={"status": "graded", "grade": 5},
                        )
                    ).status_code == 403
                    returned = await public.put(
                        review_path,
                        headers=headers(teacher),
                        json={"status": "returned", "teacher_comment": "Исправь"},
                    )
                    assert returned.status_code == 200, returned.text
                    response = await public.post(
                        path,
                        headers={**headers(student), "Idempotency-Key": "second"},
                        json={"answer_text": "Исправил"},
                    )
                    assert response.status_code == 201, response.text
                    second = response.json()
                    assert second["attempt_number"] == 2
                    response = await public.put(
                        f"{path}/{second['id']}/review",
                        headers=headers(teacher),
                        json={"status": "graded", "grade": 5},
                    )
                    assert (
                        response.status_code == 200 and response.json()["grade"] == 5
                    ), response.text
                    latest = await public.get(path, headers=headers(teacher))
                    assert len(latest.json()) == 1
                    history = await public.get(
                        path,
                        headers=headers(teacher),
                        params={"student_id": str(student.id)},
                    )
                    assert [row["attempt_number"] for row in history.json()] == [2, 1]
                    assert all(len(ids) == 1 for ids in names_calls)
                    state["class_id"] = 8
                    assert (
                        await public.get(path, headers=headers(student))
                    ).status_code == 404
                    state["assigned"] = False
                    assert (
                        await public.get(path, headers=headers(teacher))
                    ).status_code == 403
        finally:
            # Только созданные этим тестом строки; рабочая база запрещена guard выше.
            from sqlalchemy import text

            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM homework_answers WHERE homework_id=:id"),
                    {"id": parent.id},
                )
                await connection.execute(
                    text("DELETE FROM homework_assignments WHERE id=:id"),
                    {"id": parent.id},
                )
            await engine.dispose()

    asyncio.run(run())
