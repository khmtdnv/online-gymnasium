"""Настоящие API/handlers/clients трёх сервисов с заменой только хранилищ и Journal."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx


def test_teacher_schedule_card_create_and_student_reads(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "homework" / "src"))
    monkeypatch.syspath_prepend(str(root / "schedule" / "src"))
    from homework_service.app import create_app as homework_app
    from homework_service.application.homework import CreateHomeworkHandler
    from homework_service.application.student_reads import (
        GetStudentHomeworkHandler,
        ListStudentHomeworkHandler,
    )
    from homework_service.application.teacher_lessons import GetTeacherLessonHandler
    from homework_service.config import HomeworkSettings
    from homework_service.infrastructure.journal_client import HttpJournalReader
    from homework_service.infrastructure.schedule_client import HttpScheduleReader
    from schedule_service.app import create_app as schedule_app
    from schedule_service.config import Settings as ScheduleSettings
    from schedule_service.domain.lesson import Lesson

    from gateway_service.app import create_app
    from gateway_service.config import GatewaySettings
    from gateway_service.domain.user import Role, User
    from gateway_service.infrastructure.homework_client import HomeworkClient
    from gateway_service.infrastructure.schedule_client import ScheduleClient
    from gateway_service.infrastructure.token_service import PyJwtTokenService

    now = datetime(2026, 10, 19, 8, tzinfo=UTC)
    lessons = {
        id: Lesson(
            id=id,
            class_id=7,
            teacher_id=UUID(int=teacher),
            subject_id=subject,
            starts_at=now + timedelta(days=days, hours=2),
            ends_at=now + timedelta(days=days, hours=3),
        )
        for id, teacher, subject, days in [(11, 1, 3, 0), (12, 2, 3, 1), (13, 1, 4, 2)]
    }
    rows = []
    state = {"assigned": True, "class_id": 7}

    async def get(id):
        return lessons.get(id)

    async def get_many(ids):
        return [lessons[id] for id in sorted(ids) if id in lessons]

    async def get_next_lesson(*, class_id, subject_id, after):
        candidates = [
            row
            for row in lessons.values()
            if row.class_id == class_id
            and row.subject_id == subject_id
            and row.starts_at > after
            and row.status == "planned"
        ]
        return (
            min(candidates, key=lambda row: (row.starts_at, row.id))
            if candidates
            else None
        )

    async def list_for_teacher(*, teacher_id, date_from, date_to):
        return sorted(
            [
                row
                for row in lessons.values()
                if row.teacher_id == teacher_id
                and date_from <= row.starts_at.date() <= date_to
            ],
            key=lambda row: (row.starts_at, row.id),
        )

    @asynccontextmanager
    async def schedule_uow():
        yield SimpleNamespace(
            lessons=SimpleNamespace(
                get=get,
                get_many=get_many,
                get_next_lesson=get_next_lesson,
                list_for_teacher=list_for_teacher,
            )
        )

    async def add(homework):
        result = replace(homework, id=len(rows) + 1, created_at=now)
        rows.append(result)
        return result

    async def list_for_lesson(id):
        return sorted(
            [
                row
                for row in rows
                if row.issued_lesson_id == id or row.due_lesson_id == id
            ],
            key=lambda row: (row.created_at, row.id),
            reverse=True,
        )

    async def list_for_class(class_id, limit, offset):
        return sorted(
            [row for row in rows if row.class_id == class_id],
            key=lambda row: (row.created_at, row.id),
            reverse=True,
        )[offset : offset + limit]

    async def get_by_id(id):
        return next((row for row in rows if row.id == id), None)

    @asynccontextmanager
    async def homework_uow():
        yield SimpleNamespace(
            homeworks=SimpleNamespace(
                add=add,
                list_for_lesson=list_for_lesson,
                list_for_class=list_for_class,
                get_by_id=get_by_id,
            )
        )

    def journal_response(request):
        assert request.headers["Authorization"] == "Bearer homework-journal"
        if "/teachers/" in request.url.path:
            if not state["assigned"]:
                return httpx.Response(404, json={})
            teacher = request.url.path.split("/")[3]
            return httpx.Response(200, json={"teacher_id": teacher, "class_id": 7})
        return httpx.Response(
            200,
            json={
                "id": 1,
                "student_id": str(UUID(int=3)),
                "class_id": state["class_id"],
                "joined_at": now.isoformat(),
                "left_at": None,
            },
        )

    async def scenario():
        schedule = schedule_app(
            ScheduleSettings(
                _env_file=None,
                database_url="unused",
                redis_url="unused",
                rabbitmq_url="unused",
                homework_service_token="homework-schedule",
                gateway_service_token="gateway-schedule",
            ),
            AsyncMock(),
            schedule_uow,
            SimpleNamespace(aclose=AsyncMock()),
        )
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=schedule), base_url="http://schedule"
            ) as schedule_http,
            httpx.AsyncClient(
                transport=httpx.MockTransport(journal_response),
                base_url="http://journal",
            ) as journal_http,
        ):
            reader = HttpScheduleReader(schedule_http, "homework-schedule")
            journal = HttpJournalReader(journal_http, "homework-journal")
            homework = homework_app(
                HomeworkSettings(
                    _env_file=None,
                    database_url="unused",
                    gateway_service_token="gateway-homework",
                ),
                AsyncMock(),
                create_homework_handler=CreateHomeworkHandler(
                    homework_uow, reader, journal, lambda: now
                ),
                get_teacher_lesson_handler=GetTeacherLessonHandler(
                    homework_uow, reader, journal
                ),
                list_student_homework_handler=ListStudentHomeworkHandler(
                    homework_uow, journal, reader
                ),
                get_student_homework_handler=GetStudentHomeworkHandler(
                    homework_uow, journal, reader
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=homework), base_url="http://homework"
            ) as homework_http:
                settings = GatewaySettings(
                    _env_file=None,
                    database_url="unused",
                    jwt_secret="x" * 32,
                    backoffice_service_token="test",
                )
                users = {
                    id: User(
                        id=UUID(int=id),
                        email=f"user{id}@example.com",
                        role=Role.STUDENT if id == 3 else Role.TEACHER,
                        password_hash="test",
                        first_name="Иван",
                        last_name="Петров",
                        is_active=True,
                    )
                    for id in (1, 2, 3)
                }

                async def get_by_id_user(id):
                    return next(
                        (user for user in users.values() if user.id == id), None
                    )

                @asynccontextmanager
                async def gateway_uow():
                    yield SimpleNamespace(
                        users=SimpleNamespace(get_by_id=get_by_id_user)
                    )

                tokens = PyJwtTokenService(settings)
                app = create_app(
                    settings,
                    AsyncMock(),
                    gateway_uow,
                    Mock(),
                    tokens,
                    homework_client=HomeworkClient(homework_http, "gateway-homework"),
                    schedule_client=ScheduleClient(schedule_http, "gateway-schedule"),
                )
                headers = {
                    id: {"Authorization": f"Bearer {tokens.issue_access(user)}"}
                    for id, user in users.items()
                }
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://gateway"
                ) as client:
                    response = await client.get(
                        "/api/v1/lessons",
                        params={"date_from": "2026-10-19", "date_to": "2026-10-25"},
                        headers=headers[1],
                    )
                    assert response.status_code == 200, response.text
                    assert [row["id"] for row in response.json()] == [11, 13]
                    response = await client.get(
                        "/api/v1/lessons/11", headers=headers[1]
                    )
                    assert response.status_code == 200, response.text
                    assert response.json()["next_lesson"]["id"] == 12
                    response = await client.post(
                        "/api/v1/lessons/11/homework",
                        headers=headers[1],
                        json={"description": "Решить задачу", "due_lesson_id": 12},
                    )
                    assert response.status_code == 201, response.text
                    assert len(rows) == 1
                    issued = await client.get("/api/v1/lessons/11", headers=headers[1])
                    due = await client.get("/api/v1/lessons/12", headers=headers[2])
                    assert (
                        issued.json()["homework_from_lesson"][0]["id"]
                        == due.json()["homework_for_lesson"][0]["id"]
                        == 1
                    )
                    assert len(rows) == 1
                    assert (
                        await client.get("/api/v1/lessons/11", headers=headers[2])
                    ).status_code == 403
                    student = await client.get("/api/v1/homework", headers=headers[3])
                    assert student.status_code == 200 and student.json()[0]["id"] == 1
                    lessons[12].starts_at += timedelta(days=1)
                    lessons[12].ends_at += timedelta(days=1)
                    moved = await client.get("/api/v1/homework/1", headers=headers[3])
                    assert (
                        datetime.fromisoformat(moved.json()["final_due_datetime"])
                        == lessons[12].starts_at
                    )
                    lessons[12].status = "canceled"
                    cancelled = await client.get(
                        "/api/v1/homework/1", headers=headers[3]
                    )
                    assert cancelled.json()["final_due_datetime"] is None
                    assert cancelled.json()["due_status"] == "lesson_cancelled"
                    state["assigned"] = False
                    assert (
                        await client.get("/api/v1/lessons/11", headers=headers[1])
                    ).status_code == 403
                    assert (
                        await client.get(
                            "/api/v1/lessons",
                            params={"date_from": "2026-10-19", "date_to": "2026-10-25"},
                            headers=headers[1],
                        )
                    ).status_code == 200
                    state["assigned"] = True
                    lessons[11].status = "canceled"
                    assert (
                        await client.get("/api/v1/lessons/11", headers=headers[1])
                    ).status_code == 200
                    assert (
                        await client.post(
                            "/api/v1/lessons/11/homework",
                            headers=headers[1],
                            json={"description": "Другое", "due_lesson_id": 12},
                        )
                    ).status_code == 403
                    state["class_id"] = 8
                    assert (
                        await client.get("/api/v1/homework", headers=headers[3])
                    ).json() == []
                    assert (
                        await client.get("/api/v1/homework/1", headers=headers[3])
                    ).status_code == 404

    asyncio.run(scenario())
