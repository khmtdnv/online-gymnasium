"""Авторизованный WebSocket симулятора и выбор учеников своего урока."""

import asyncio
import time
from collections import deque
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import RequireRoles
from gateway_service.api.tuition_access import check_student_tuition
from gateway_service.application.auth import (
    GetCurrentUserCommand,
    GetCurrentUserHandler,
    GetCurrentUserResult,
)
from gateway_service.application.errors import AuthenticationError
from gateway_service.application.pen import PenAuthentication, PenBatch
from gateway_service.application.teacher_lessons import ScheduleUnavailableError
from gateway_service.domain.user import Role
from gateway_service.infrastructure.journal_client import JournalUnavailableError
from gateway_service.infrastructure.pen_client import (
    PenRequestError,
    PenUnavailableError,
)

router = APIRouter(prefix="/api/v1/pen", tags=["pen"])
LessonId = Annotated[int, Path(ge=1, le=2147483647)]


async def get_pen_lesson(app, lesson_id):
    """Отсутствие владельца не заменяет разрешение на доступ по старым данным."""
    if app.state.schedule_client is None or app.state.journal_client is None:
        raise HTTPException(503, "Pen authorization unavailable")
    lesson = await app.state.schedule_client.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(404, "Lesson not found")
    if lesson.status != "planned":
        raise HTTPException(403, "Lesson is canceled")
    return lesson


async def check_pen_access(app, user, lesson_id: int, student_id: UUID) -> None:
    """Проверяет реальных владельцев до чтения истории и перед записью.

    Args:
        app: Gateway с настроенными readers владельцев.
        user: Активный пользователь после проверки JWT и БД Gateway.
        lesson_id: Урок Schedule.
        student_id: Чья страница запрошена.

    Raises:
        HTTPException: Чужой пользователь/урок/класс либо интеграция недоступна.
    """
    if user.role not in {Role.STUDENT, Role.TEACHER} or (
        user.role == Role.STUDENT and user.id != student_id
    ):
        raise HTTPException(403, "Pen access denied")
    await check_student_tuition(app, user)
    lesson = await get_pen_lesson(app, lesson_id)
    if user.role == Role.TEACHER and lesson.teacher_id != user.id:
        raise HTTPException(403, "Pen access denied")
    if (
        await app.state.journal_client.get_current_class_id(student_id)
        != lesson.class_id
    ):
        raise HTTPException(403, "Student class changed")


@router.get("/lessons/{lesson_id}/students")
async def lesson_students(
    request: Request,
    response: Response,
    lesson_id: LessonId,
    user: Annotated[GetCurrentUserResult, Depends(RequireRoles((Role.TEACHER,)))],
) -> list[dict]:
    """Возвращает имена текущего класса урока без лишних HTTP-запросов на ученика."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        lesson = await get_pen_lesson(request.app, lesson_id)
        if lesson.teacher_id != user.id:
            raise HTTPException(403, "Lesson access denied")
        ids = await request.app.state.journal_client.list_current_student_ids(
            lesson.class_id
        )
        async with request.app.state.uow_factory() as uow:
            users = await uow.users.get_by_ids(ids)
        return [
            {
                "id": row.id,
                "name": " ".join(
                    part
                    for part in (row.last_name, row.first_name, row.middle_name)
                    if part
                ),
            }
            for row in users
            if row.role == Role.STUDENT and row.is_active
        ]
    except (ScheduleUnavailableError, JournalUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(503, "Pen authorization unavailable") from exc


@router.websocket("/lessons/{lesson_id}/students/{student_id}")
async def pen_socket(ws: WebSocket, lesson_id: LessonId, student_id: UUID) -> None:
    """ACK следует commit; teacher читает сохранённые пачки каждые0.5с.

    Origin и первое сообщение проверяются до любого чтения Pen. Действующие
    подключения перепроверяют JWT/роль/владельцев минимум каждые5с; запись — всегда.
    SQL-сессия ни в одной итерации не переживает сетевое ожидание.
    """
    app = ws.app
    if ws.headers.get("origin") != app.state.settings.public_origin:
        await ws.close(code=1008)
        return
    # Счётчики принадлежат конкретному приложению/процессу, не всем тестовым app.
    if not hasattr(app.state, "pen_connections"):
        app.state.pen_connections = {}
        app.state.pen_total = 0
    if app.state.pen_total >= 100:
        await ws.close(code=1013)
        return
    app.state.pen_total += 1
    user_id = None
    counted = False
    try:
        await ws.accept()
        raw = await asyncio.wait_for(ws.receive_text(), timeout=5)
        if len(raw.encode()) > 65536:
            raise HTTPException(413, "Pen message too large")
        auth = PenAuthentication.model_validate_json(raw)
        handler = GetCurrentUserHandler(app.state.uow_factory, app.state.token_service)

        async def authorize():
            user = await handler.handle(
                GetCurrentUserCommand(access_token=auth.access_token)
            )
            await check_pen_access(app, user, lesson_id, student_id)
            return user

        user = await authorize()
        user_id = user.id
        if app.state.pen_connections.get(user_id, 0) >= 2:
            raise HTTPException(429, "Too many pen connections")
        app.state.pen_connections[user_id] = (
            app.state.pen_connections.get(user_id, 0) + 1
        )
        counted = True
        client = app.state.pen_client
        if client is None:
            raise HTTPException(503, "Pen unavailable")
        cursor = auth.after
        checked_at = time.monotonic()

        async def send_history():
            nonlocal cursor, checked_at, user
            while True:
                if time.monotonic() - checked_at >= 5:
                    user = await authorize()
                    checked_at = time.monotonic()
                rows = await client.history(lesson_id, student_id, after=cursor)
                for row in rows:
                    await asyncio.wait_for(
                        ws.send_json(
                            {"type": "batch", "batch": row.model_dump(mode="json")}
                        ),
                        timeout=5,
                    )
                    cursor = row.sequence
                if len(rows) < 100:
                    break

        await send_history()
        await ws.send_json({"type": "ready", "after": cursor})
        writes = deque()
        while True:
            if time.monotonic() - checked_at >= 5:
                user = await authorize()
                checked_at = time.monotonic()
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.5)
            except TimeoutError:
                if user.role == Role.TEACHER:
                    await send_history()
                continue
            if user.role != Role.STUDENT:
                raise HTTPException(403, "Teacher pen is read-only")
            if len(raw.encode()) > 65536:
                raise HTTPException(413, "Pen message too large")
            now = time.monotonic()
            while writes and writes[0] < now - 1:
                writes.popleft()
            if len(writes) >= 10:
                raise HTTPException(429, "Pen rate exceeded")
            writes.append(now)
            batch = PenBatch.model_validate_json(raw)
            user = await authorize()
            checked_at = time.monotonic()
            if user.role != Role.STUDENT:
                raise HTTPException(403, "Teacher pen is read-only")
            saved = await client.append(lesson_id, student_id, batch)
            await ws.send_json({"type": "ack", "batch": saved.model_dump(mode="json")})
    except WebSocketDisconnect:
        pass
    except AuthenticationError:
        await ws.close(code=4401)
    except HTTPException as exc:
        await ws.close(
            code={403: 4403, 404: 4404, 409: 4409, 413: 4413, 429: 4429}.get(
                exc.status_code, 1013
            )
        )
    except PenRequestError as exc:
        await ws.close(code=4409 if exc.status_code == 409 else 4413)
    except ValidationError, ValueError, TimeoutError:
        await ws.close(code=1008)
    except (
        PenUnavailableError,
        ScheduleUnavailableError,
        JournalUnavailableError,
        SQLAlchemyError,
        OSError,
    ):
        await ws.close(code=1013)
    finally:
        app.state.pen_total -= 1
        if counted:
            count = app.state.pen_connections[user_id] - 1
            if count:
                app.state.pen_connections[user_id] = count
            else:
                del app.state.pen_connections[user_id]
