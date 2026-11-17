"""Закрытая карточка урока ученика с актуальной проверкой класса."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.ports.errors import (
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.student_lessons import GetStudentLessonQuery
from homework_service.application.teacher_lessons import TeacherLessonResult

router = APIRouter(include_in_schema=False, dependencies=[Depends(require_gateway)])


@router.get("/internal/student-lessons/{lesson_id}", response_model=TeacherLessonResult)
async def get_student_lesson(
    request: Request,
    lesson_id: Annotated[int, Path(ge=1, le=2147483647)],
    student_id: Annotated[UUID, Header(alias="X-Student-ID")],
) -> TeacherLessonResult:
    """Не раскрывает существование чужого урока и не скрывает недоступность владельца."""
    handler = request.app.state.get_student_lesson_handler
    if handler is None:
        raise unavailable()
    try:
        return await handler.handle(
            GetStudentLessonQuery(student_id=student_id, lesson_id=lesson_id)
        )
    except HomeworkNotFoundError as exc:
        raise HomeworkHTTPError(404, "lesson_not_found", "Lesson not found") from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc
