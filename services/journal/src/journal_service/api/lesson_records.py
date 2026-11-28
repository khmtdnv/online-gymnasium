"""Внутренние HTTP-ручки записей урока: запись учителя и чтения дневника."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from journal_service.api.dependencies import (
    get_last_entry_date_handler,
    get_list_lesson_entries_handler,
    get_list_student_diary_entries_handler,
    get_record_lesson_entries_handler,
    get_subject_averages_handler,
)
from journal_service.api.security import (
    RequireServicePermission,
    get_lesson_record_actor,
)
from journal_service.application.lesson_records import (
    MAX_LESSON_ID,
    MAX_QUARTER,
    AttendanceEntry,
    AttendanceStatus,
    GetLastEntryDateHandler,
    GetSubjectAveragesHandler,
    GradeEntry,
    GradeKind,
    LessonContext,
    LessonRecordConflictError,
    LessonRecordValidationError,
    ListLessonEntriesHandler,
    ListStudentDiaryEntriesHandler,
    RecordLessonEntriesCommand,
    RecordLessonEntriesHandler,
)

router = APIRouter(
    prefix="/internal",
    include_in_schema=False,
)

LessonId = Annotated[int, Path(ge=1, le=MAX_LESSON_ID)]
StudentId = Annotated[UUID, Path()]
ActorId = Annotated[UUID, Depends(get_lesson_record_actor)]
Quarter = Annotated[int, Query(ge=1, le=MAX_QUARTER)]


class RecordLessonEntriesBody(BaseModel):
    """Тело записи урока без lesson_id: контекст, посещаемость, оценки."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context: LessonContext
    attendance: list[AttendanceEntry] = Field(max_length=50, default_factory=list)
    grades: list[GradeEntry] = Field(max_length=100, default_factory=list)


class AttendanceResponse(BaseModel):
    """Сохранённая посещаемость одного ученика."""

    lesson_id: int
    lesson_date: date
    class_id: int
    student_id: UUID
    status: AttendanceStatus
    author_id: UUID
    generator: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class GradeResponse(BaseModel):
    """Сохранённая оценка одного ученика."""

    lesson_id: int
    lesson_date: date
    class_id: int
    subject_id: int
    student_id: UUID
    grade: int
    kind: GradeKind
    author_id: UUID
    generator: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class LessonEntriesResponse(BaseModel):
    """Записи урока или окна дат."""

    attendance: list[AttendanceResponse]
    grades: list[GradeResponse]


class SubjectAverageResponse(BaseModel):
    """Средняя и четвертная оценка по предмету."""

    subject_id: int
    average: float
    grade_count: int
    quarter_grade: int


class LastEntryDateResponse(BaseModel):
    """Якорь дневника с четвертью опорной даты."""

    last_entry_date: date | None
    quarter: int
    quarter_from: date
    quarter_to: date


@router.post(
    "/lessons/{lesson_id}/entries",
    response_model=LessonEntriesResponse,
    dependencies=[Depends(RequireServicePermission("lesson-records:write"))],
)
async def record_lesson_entries(
    lesson_id: LessonId,
    body: RecordLessonEntriesBody,
    actor: ActorId,
    handler: Annotated[
        RecordLessonEntriesHandler, Depends(get_record_lesson_entries_handler)
    ],
) -> LessonEntriesResponse:
    """Заменяет записи урока пакетом учителя одной транзакцией.

    Args:
        lesson_id: Урок, записи которого заменяются.
        body: Контекст урока, посещаемость и оценки пакета.
        actor: Учитель из заголовка X-User-ID.
        handler: Обработчик команды записи.

    Returns:
        Полное состояние записей урока после замены.

    Raises:
        HTTPException: 503 при сбое базы.
    """
    command = RecordLessonEntriesCommand(
        lesson_id=lesson_id,
        context=body.context,
        attendance=body.attendance,
        grades=body.grades,
    )
    try:
        result = await handler.handle(command, actor_id=actor)
    except LessonRecordConflictError:
        raise HTTPException(status_code=409, detail="Lesson teacher conflict") from None
    except LessonRecordValidationError:
        raise HTTPException(
            status_code=422, detail="Invalid lesson record data"
        ) from None
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc
    return LessonEntriesResponse(
        attendance=[
            AttendanceResponse(**entry.model_dump()) for entry in result.attendance
        ],
        grades=[GradeResponse(**entry.model_dump()) for entry in result.grades],
    )


@router.get(
    "/students/{student_id}/diary-entries",
    response_model=LessonEntriesResponse,
    dependencies=[Depends(RequireServicePermission("diary:read"))],
)
async def list_student_diary_entries(
    student_id: StudentId,
    handler: Annotated[
        ListStudentDiaryEntriesHandler,
        Depends(get_list_student_diary_entries_handler),
    ],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    quarter: Annotated[int | None, Query(ge=1, le=MAX_QUARTER)] = None,
) -> LessonEntriesResponse:
    """Читает записи ученика окном: датами или номером четверти.

    Args:
        student_id: Ученик, чьи записи читаются.
        date_from: Начальная дата окна включительно.
        date_to: Конечная дата окна включительно.
        quarter: Номер четверти вместо дат окна.
        handler: Обработчик чтения окна.

    Returns:
        Посещаемость и оценки окна.

    Raises:
        HTTPException: 422 при неверном окне, 503 при сбое базы.
    """
    try:
        result = await handler.handle(student_id, date_from, date_to, quarter)
    except LessonRecordValidationError:
        raise HTTPException(status_code=422, detail="Invalid diary window") from None
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc
    return LessonEntriesResponse(
        attendance=[
            AttendanceResponse(**entry.model_dump()) for entry in result.attendance
        ],
        grades=[GradeResponse(**entry.model_dump()) for entry in result.grades],
    )


@router.get(
    "/students/{student_id}/last-entry-date",
    response_model=LastEntryDateResponse,
    dependencies=[Depends(RequireServicePermission("diary:read"))],
)
async def get_last_entry_date(
    student_id: StudentId,
    handler: Annotated[GetLastEntryDateHandler, Depends(get_last_entry_date_handler)],
    reference: Annotated[date | None, Query()] = None,
) -> LastEntryDateResponse:
    """Возвращает якорь дневника: последнюю запись и четверть.

    Args:
        student_id: Ученик, чья последняя запись ищется.
        reference: Опорная дата четверти, если нужна именно она.
        handler: Обработчик чтения якоря дневника.

    Returns:
        Дата последней записи, номер и границы четверти опорной даты.

    Raises:
        HTTPException: 422 при опорной дате вне года, 503 при сбое базы.
    """
    try:
        return await handler.handle(student_id, reference)
    except LessonRecordValidationError:
        raise HTTPException(status_code=422, detail="Invalid reference date") from None
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc


@router.get(
    "/students/{student_id}/subject-averages",
    response_model=list[SubjectAverageResponse],
    dependencies=[Depends(RequireServicePermission("diary:read"))],
)
async def get_subject_averages(
    student_id: StudentId,
    quarter: Quarter,
    handler: Annotated[
        GetSubjectAveragesHandler, Depends(get_subject_averages_handler)
    ],
) -> list[SubjectAverageResponse]:
    """Считает средние и четвертные оценки ученика за четверть.

    Args:
        student_id: Ученик, чьи средние считаются.
        quarter: Номер четверти от 1 до 4.
        handler: Обработчик средних.

    Returns:
        Средняя, число оценок и четвертная по каждому предмету.

    Raises:
        HTTPException: 422 при неверном номере четверти, 503 при сбое базы.
    """
    try:
        results = await handler.handle(student_id, quarter)
    except LessonRecordValidationError:
        raise HTTPException(status_code=422, detail="Invalid quarter") from None
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc
    return [
        SubjectAverageResponse(
            subject_id=result.subject_id,
            average=float(result.average),
            grade_count=result.grade_count,
            quarter_grade=result.quarter_grade,
        )
        for result in results
    ]


@router.get(
    "/lessons/{lesson_id}/entries",
    response_model=LessonEntriesResponse,
    dependencies=[Depends(RequireServicePermission("lesson-entries:read"))],
)
async def list_lesson_entries(
    lesson_id: LessonId,
    handler: Annotated[
        ListLessonEntriesHandler, Depends(get_list_lesson_entries_handler)
    ],
) -> LessonEntriesResponse:
    """Читает записи одного урока для формы правки.

    Args:
        lesson_id: Урок, записи которого читаются.
        handler: Обработчик чтения записей урока.

    Returns:
        Посещаемость и оценки урока; пустые списки без записей.

    Raises:
        HTTPException: 503 при сбое базы.
    """
    try:
        result = await handler.handle(lesson_id)
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Journal unavailable") from exc
    return LessonEntriesResponse(
        attendance=[
            AttendanceResponse(**entry.model_dump()) for entry in result.attendance
        ],
        grades=[GradeResponse(**entry.model_dump()) for entry in result.grades],
    )
