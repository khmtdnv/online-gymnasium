"""Публичная выдача ДЗ от действующего преподавателя."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import (
    CreateHomeworkRequest,
    HomeworkRequestError,
    HomeworkResult,
    HomeworkUnavailableError,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.homework_client import HomeworkClient

router = APIRouter(prefix="/api/v1/lessons", tags=["homework"])
teacher_only = RequireRoles(allowed_roles=(Role.TEACHER,))


def get_homework_client(request: Request) -> HomeworkClient:
    """Возвращает подключённый Homework либо безопасный 503.

    Args:
        request: Запрос с ресурсами процесса.

    Returns:
        Клиент закрытого API Homework.

    Raises:
        HTTPException: Интеграция не настроена.
    """
    client = request.app.state.homework_client
    if client is None:
        raise HTTPException(503, "Service unavailable")
    return client


@router.post("/{lesson_id}/homework", status_code=201, response_model=HomeworkResult)
async def create_homework(
    lesson_id: Annotated[int, Path(ge=1, le=2147483647)],
    body: CreateHomeworkRequest,
    teacher: Annotated[GetCurrentUserResult, Depends(teacher_only)],
    client: Annotated[HomeworkClient, Depends(get_homework_client)],
) -> HomeworkResult:
    """Передаёт данные выдачи с автором из проверенного пользователя Gateway.

    Args:
        lesson_id: Урок выдачи из адреса запроса.
        body: Описание и один срок.
        teacher: Активный пользователь с актуальной ролью teacher.
        client: Клиент владельца заданий.

    Returns:
        Проверенный результат создания задания.

    Raises:
        HTTPException: Бизнес-отказ владельца либо недоступность сервиса.
    """
    try:
        return await client.create_homework(
            teacher_id=teacher.id,
            issued_lesson_id=lesson_id,
            files=body.files,
            **body.model_dump(exclude={"files"}),
        )
    except HomeworkRequestError as exc:
        messages = {
            "access_denied": "Access denied",
            "lesson_not_found": "Lesson not found",
            "homework_already_exists": "Homework already exists",
            "invalid_homework_data": "Invalid homework data",
        }
        raise HTTPException(exc.status_code, messages[exc.code]) from exc
    except HomeworkUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc
