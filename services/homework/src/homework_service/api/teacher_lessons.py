"""Закрытая карточка урока для доверенного преподавателя Gateway."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.teacher_lessons import (
    GetTeacherLessonHandler,
    GetTeacherLessonQuery,
    TeacherLessonResult,
)

router = APIRouter(
    prefix="/internal/teacher-lessons",
    include_in_schema=False,
    dependencies=[Depends(require_gateway)],
)


def get_teacher_lesson_handler(request: Request) -> GetTeacherLessonHandler:
    """Возвращает собранную зависимость либо503 при неполной конфигурации."""
    handler = request.app.state.get_teacher_lesson_handler
    if handler is None:
        raise unavailable()
    return handler


@router.get("/{lesson_id}", response_model=TeacherLessonResult)
async def get_teacher_lesson(
    lesson_id: Annotated[int, Path(ge=1, le=2147483647)],
    teacher_id: Annotated[UUID, Header(alias="X-Teacher-ID")],
    handler: Annotated[GetTeacherLessonHandler, Depends(get_teacher_lesson_handler)],
) -> TeacherLessonResult:
    """Читает карточку после служебной аутентификации и проверки назначения.

    Args:
        lesson_id: ID открытого урока.
        teacher_id: UUID, установленный Gateway.
        handler: Прикладной сценарий карточки.

    Returns:
        Проверенная карточка урока.

    Raises:
        HomeworkHTTPError: Нет доступа403, урока404 либо зависимость недоступна503.
    """
    try:
        return await handler.handle(
            GetTeacherLessonQuery(teacher_id=teacher_id, lesson_id=lesson_id)
        )
    except HomeworkAccessDeniedError as exc:
        raise HomeworkHTTPError(403, "access_denied", "Access denied") from exc
    except LessonNotFoundError as exc:
        raise HomeworkHTTPError(404, "lesson_not_found", "Lesson not found") from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc
