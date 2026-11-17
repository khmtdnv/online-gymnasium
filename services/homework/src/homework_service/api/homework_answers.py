"""Закрытый API ответов; принимает личность только от аутентифицированного Gateway."""

from contextlib import contextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.homework_answers import (
    HomeworkAnswerInput,
    HomeworkAnswerResult,
    HomeworkAnswerReviewInput,
    HomeworkAnswersQuery,
    ReviewHomeworkAnswerCommand,
    SubmitHomeworkAnswerCommand,
)
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkAnswerConflictError,
    HomeworkFileNotReadyError,
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)


def private_answer_response(response: Response) -> None:
    """Не позволяет HTTP-кешу сохранять ученические ответы."""
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/internal/homework",
    include_in_schema=False,
    dependencies=[Depends(require_gateway), Depends(private_answer_response)],
)
ID = Annotated[int, Path(ge=1, le=2147483647)]
UserID = Annotated[UUID, Header(alias="X-User-ID")]
UserRole = Annotated[Literal["student", "teacher"], Header(alias="X-User-Role")]


@contextmanager
def answer_errors():
    """Переводит только известные ошибки границы в безопасный HTTP-контракт."""
    try:
        yield
    except HomeworkNotFoundError as exc:
        raise HomeworkHTTPError(
            404, "homework_answer_not_found", "Answer not found"
        ) from exc
    except HomeworkAccessDeniedError as exc:
        raise HomeworkHTTPError(403, "access_denied", "Access denied") from exc
    except HomeworkAnswerConflictError as exc:
        raise HomeworkHTTPError(
            409, "homework_answer_conflict", "Answer state conflict"
        ) from exc
    except HomeworkFileNotReadyError as exc:
        raise HomeworkHTTPError(
            409, "homework_file_not_ready", "File not ready"
        ) from exc
    except ValueError as exc:
        raise HomeworkHTTPError(
            422, "invalid_homework_answer", "Invalid answer"
        ) from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc


def answer_handler(request: Request, name: str):
    """Отказывает503 при неполной настройке, а не при первом случайном обращении."""
    handler = getattr(request.app.state, name, None)
    if handler is None:
        raise unavailable()
    return handler


@router.post(
    "/{homework_id}/answers", response_model=HomeworkAnswerResult, status_code=201
)
async def submit_answer(
    request: Request,
    response: Response,
    homework_id: ID,
    body: HomeworkAnswerInput,
    user_id: UserID,
    role: UserRole,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[!-~]+$"
        ),
    ],
) -> HomeworkAnswerResult:
    """Создаёт попытку авторизованного ученика либо возвращает её безопасный повтор."""
    if role != "student":
        raise HomeworkHTTPError(403, "access_denied", "Access denied")
    with answer_errors():
        result = await answer_handler(request, "submit_homework_answer_handler").handle(
            SubmitHomeworkAnswerCommand(
                student_id=user_id,
                homework_id=homework_id,
                idempotency_key=idempotency_key,
                **body.model_dump(),
            )
        )
    response.status_code = 201 if result.created else 200
    return result.answer


@router.get("/{homework_id}/answers", response_model=list[HomeworkAnswerResult])
async def list_answers(
    request: Request,
    homework_id: ID,
    user_id: UserID,
    role: UserRole,
    student_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> list[HomeworkAnswerResult]:
    """Читает свою историю либо ограниченную страницу разрешённых работ учителя."""
    with answer_errors():
        return await answer_handler(request, "read_homework_answers_handler").handle(
            HomeworkAnswersQuery(
                user_id=user_id,
                role=role,
                homework_id=homework_id,
                student_id=student_id,
                limit=limit,
                offset=offset,
            )
        )


@router.get("/{homework_id}/answers/{answer_id}", response_model=HomeworkAnswerResult)
async def get_answer(
    request: Request, homework_id: ID, answer_id: ID, user_id: UserID, role: UserRole
) -> HomeworkAnswerResult:
    """Не позволяет прочитать чужую попытку по прямому ID."""
    with answer_errors():
        results = await answer_handler(request, "read_homework_answers_handler").handle(
            HomeworkAnswersQuery(
                user_id=user_id, role=role, homework_id=homework_id, answer_id=answer_id
            )
        )
    return results[0]


@router.put(
    "/{homework_id}/answers/{answer_id}/review", response_model=HomeworkAnswerResult
)
async def review_answer(
    request: Request,
    homework_id: ID,
    answer_id: ID,
    body: HomeworkAnswerReviewInput,
    user_id: UserID,
    role: UserRole,
) -> HomeworkAnswerResult:
    """Однократно сохраняет решение преподавателя, не принимая reviewer_id из JSON."""
    if role != "teacher":
        raise HomeworkHTTPError(403, "access_denied", "Access denied")
    with answer_errors():
        return await answer_handler(request, "review_homework_answer_handler").handle(
            ReviewHomeworkAnswerCommand(
                teacher_id=user_id,
                homework_id=homework_id,
                answer_id=answer_id,
                **body.model_dump(),
            )
        )
