import hashlib
import json
from datetime import date as Date
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, status
from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from schedule_service.api.dependencies import (
    get_cancel_lesson_handler,
    get_create_lesson_handler,
    get_list_lessons_handler,
    get_update_lesson_handler,
)
from schedule_service.application.cancel_lesson import (
    CancelLessonCommand,
    CancelLessonHandler,
)
from schedule_service.application.create_lesson import (
    CreateLessonCommand,
    CreateLessonHandler,
)
from schedule_service.application.errors import (
    IdempotencyKeyReuse,
    LessonNotFound,
    ScheduleCacheBusy,
    ScheduleConflict,
    VersionConflict,
)
from schedule_service.application.list_lessons import (
    ListLessonsHandler,
    ListLessonsQuery,
)
from schedule_service.application.update_lesson import (
    UpdateLessonCommand,
    UpdateLessonHandler,
)
from schedule_service.domain.lesson import InvalidLessonInterval, LessonAlreadyCanceled

router = APIRouter(prefix="/lessons", tags=["lessons"])


class CreateLessonRequest(BaseModel):
    """Данные для создания урока и проверки повторного запроса."""

    class_id: Annotated[int, Field(gt=0, strict=True)]
    teacher_id: UUID
    subject_id: Annotated[int, Field(gt=0, strict=True)]
    starts_at: AwareDatetime
    ends_at: AwareDatetime


class UpdateLessonRequest(BaseModel):
    """Новый интервал урока и версия, которую ожидает клиент."""

    starts_at: AwareDatetime
    ends_at: AwareDatetime
    expected_version: Annotated[int, Field(gt=0, strict=True)]


class CancelLessonRequest(BaseModel):
    """Данные отмены урока с ожидаемой версией."""

    expected_version: Annotated[int, Field(gt=0, strict=True)]


class LessonResponse(BaseModel):
    """Данные урока, которые API возвращает клиенту."""

    id: int
    class_id: int
    teacher_id: UUID
    subject_id: int
    starts_at: datetime
    ends_at: datetime
    status: str
    version: int


@router.post("", status_code=201, response_model=LessonResponse)
async def create_lesson(
    request_model: CreateLessonRequest,
    handler: Annotated[CreateLessonHandler, Depends(get_create_lesson_handler)],
    idempotency_key: Annotated[str | None, Header()] = None,
):
    """Создаёт урок, используя хеш тела для проверки повторного запроса.

    Args:
        request_model: Проверенные данные тела HTTP-запроса.
        handler: Обработчик прикладного сценария.
        idempotency_key: Необязательный ключ, связывающий повторные запросы.

    Returns:
        Данные созданного либо повторно найденного урока.

    Raises:
        HTTPException: Недопустимый интервал (422), конфликт расписания или ключа (409).
    """
    payload = request_model.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(serialized.encode()).hexdigest()
    try:
        command = CreateLessonCommand(
            class_id=request_model.class_id,
            teacher_id=request_model.teacher_id,
            subject_id=request_model.subject_id,
            starts_at=request_model.starts_at,
            ends_at=request_model.ends_at,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="starts_at must be before ends_at"
        ) from exc
    try:
        response = await handler.handle(command)
    except InvalidLessonInterval as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="starts_at must be before ends_at",
        ) from exc
    except ScheduleConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson conflicts with existing schedule",
        ) from exc
    except IdempotencyKeyReuse as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for another request",
        ) from exc

    return response


@router.patch("/{lesson_id}", response_model=LessonResponse)
async def update_lesson(
    lesson_id: Annotated[int, Path(gt=0)],
    request_model: UpdateLessonRequest,
    handler: Annotated[UpdateLessonHandler, Depends(get_update_lesson_handler)],
):
    """Переносит урок с проверкой версии, переданной клиентом.

    Args:
        lesson_id: ID урока в базе расписания.
        request_model: Проверенные данные тела HTTP-запроса.
        handler: Обработчик прикладного сценария.

    Returns:
        Обновлённый урок.

    Raises:
        HTTPException: Урок не найден (404), интервал неверен (422) или возник конфликт
            (409).
    """
    try:
        command = UpdateLessonCommand(
            lesson_id=lesson_id,
            starts_at=request_model.starts_at,
            ends_at=request_model.ends_at,
            expected_version=request_model.expected_version,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="starts_at must be before ends_at"
        ) from exc
    try:
        return await handler.handle(command)
    except InvalidLessonInterval as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="starts_at must be before ends_at",
        ) from exc
    except LessonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        ) from exc
    except VersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson version conflict",
        ) from exc
    except ScheduleConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson conflicts with existing schedule",
        ) from exc


@router.post("/{lesson_id}/cancel", response_model=LessonResponse)
async def cancel_lesson(
    lesson_id: Annotated[int, Path(gt=0)],
    request_model: CancelLessonRequest,
    handler: Annotated[CancelLessonHandler, Depends(get_cancel_lesson_handler)],
):
    """Отменяет урок с проверкой ожидаемой версии.

    Args:
        lesson_id: ID урока в базе расписания.
        request_model: Проверенные данные тела HTTP-запроса.
        handler: Обработчик прикладного сценария.

    Returns:
        Данные отменённого урока.

    Raises:
        HTTPException: Урок не найден (404), уже отменён или версия устарела (409).
    """
    command = CancelLessonCommand(
        lesson_id=lesson_id,
        expected_version=request_model.expected_version,
    )
    try:
        return await handler.handle(command)
    except LessonAlreadyCanceled as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson is already canceled",
        ) from exc
    except LessonNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        ) from exc
    except VersionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lesson version conflict",
        ) from exc


@router.get("", response_model=list[LessonResponse])
async def list_lessons(
    class_id: Annotated[int, Query(gt=0)],
    date: Date,
    handler: Annotated[ListLessonsHandler, Depends(get_list_lessons_handler)],
):
    """Возвращает плановое расписание класса на день.

    Args:
        class_id: ID класса, для которого выполняется операция.
        date: Календарная дата запрашиваемого расписания.
        handler: Обработчик прикладного сценария.

    Returns:
        Список уроков выбранного класса.

    Raises:
        HTTPException: Кеш не удалось заполнить за лимит попыток; HTTP-статус 503.
    """
    try:
        query = ListLessonsQuery(class_id=class_id, day=date)
        return await handler.handle(query)
    except ScheduleCacheBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schedule cache is busy",
        ) from exc
