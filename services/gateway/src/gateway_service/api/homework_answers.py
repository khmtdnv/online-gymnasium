"""Публичная сдача и проверка: автор и роль берутся только из Gateway."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.file_download import FileDownloadResponse
from gateway_service.api.file_upload import read_upload
from gateway_service.api.homework import get_homework_client, teacher_only
from gateway_service.api.homework_files import file_users, get_homework_file_client
from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import HomeworkUnavailableError
from gateway_service.application.homework_answers import (
    HomeworkAnswerFileResult,
    HomeworkAnswerInput,
    HomeworkAnswerResult,
    HomeworkAnswerReviewInput,
    NamedHomeworkAnswerResult,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.homework_client import HomeworkClient
from gateway_service.infrastructure.homework_file_client import HomeworkFileClient


def private_answer_response(response: Response) -> None:
    """Запрещает сохранять личные работы и оценки в HTTP-кеше."""
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/api/v1/homework",
    tags=["homework"],
    dependencies=[Depends(private_answer_response)],
)
ID = Annotated[int, Path(ge=1, le=2147483647)]
User = Annotated[GetCurrentUserResult, Depends(file_users)]
Student = Annotated[
    GetCurrentUserResult, Depends(RequireRoles(allowed_roles=(Role.STUDENT,)))
]
Teacher = Annotated[GetCurrentUserResult, Depends(teacher_only)]
Client = Annotated[HomeworkClient, Depends(get_homework_client)]
Files = Annotated[HomeworkFileClient, Depends(get_homework_file_client)]


async def named_answers(
    request: Request, answers: list[HomeworkAnswerResult]
) -> list[NamedHomeworkAnswerResult]:
    """Дополняет разрешённую страницу одним запросом ФИО к собственной базе."""
    if not answers:
        return []
    async with request.app.state.uow_factory() as uow:
        users = await uow.users.get_by_ids(
            list({answer.student_id for answer in answers})
        )
    names = {
        user.id: " ".join(
            part for part in (user.last_name, user.first_name, user.middle_name) if part
        )
        for user in users
    }
    return [
        NamedHomeworkAnswerResult(
            **answer.model_dump(),
            student_name=names.get(answer.student_id, "Ученик (запись недоступна)"),
        )
        for answer in answers
    ]


@router.post(
    "/{homework_id}/answers", response_model=NamedHomeworkAnswerResult, status_code=201
)
async def submit_answer(
    request: Request,
    response: Response,
    homework_id: ID,
    body: HomeworkAnswerInput,
    student: Student,
    client: Client,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[!-~]+$"
        ),
    ],
) -> NamedHomeworkAnswerResult:
    """Отправляет ответ с постоянным ключом; повтор не создаёт новую попытку."""
    try:
        answer, created = await client.answers.submit(
            student.id, homework_id, idempotency_key, body
        )
        response.status_code = 201 if created else 200
        return (await named_answers(request, [answer]))[0]
    except (HomeworkUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.get("/{homework_id}/answers", response_model=list[NamedHomeworkAnswerResult])
async def list_answers(
    request: Request,
    homework_id: ID,
    user: User,
    client: Client,
    student_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> list[NamedHomeworkAnswerResult]:
    """Ученику возвращает историю, учителю — последние работы или историю ученика."""
    if user.role == Role.STUDENT and student_id is not None:
        raise HTTPException(403, "Access denied")
    try:
        answers = await client.answers.list_answers(
            user.id,
            user.role.value,
            homework_id,
            student_id=student_id,
            limit=limit,
            offset=offset,
        )
        return await named_answers(request, answers)
    except (HomeworkUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.get(
    "/{homework_id}/answers/{answer_id}", response_model=NamedHomeworkAnswerResult
)
async def get_answer(
    request: Request, homework_id: ID, answer_id: ID, user: User, client: Client
) -> NamedHomeworkAnswerResult:
    """Читает одну попытку после свежей проверки доступа владельцем."""
    try:
        answer = await client.answers.get_answer(
            user.id, user.role.value, homework_id, answer_id
        )
        return (await named_answers(request, [answer]))[0]
    except (HomeworkUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.put(
    "/{homework_id}/answers/{answer_id}/review",
    response_model=NamedHomeworkAnswerResult,
)
async def review_answer(
    request: Request,
    homework_id: ID,
    answer_id: ID,
    body: HomeworkAnswerReviewInput,
    teacher: Teacher,
    client: Client,
) -> NamedHomeworkAnswerResult:
    """Сохраняет оценку либо возврат; повтор одинакового решения безопасен."""
    try:
        answer = await client.answers.review(teacher.id, homework_id, answer_id, body)
        return (await named_answers(request, [answer]))[0]
    except (HomeworkUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.put(
    "/{homework_id}/answers/{answer_id}/files/{file_id}",
    response_model=HomeworkAnswerFileResult,
)
async def upload_answer_file(
    request: Request,
    homework_id: ID,
    answer_id: ID,
    file_id: ID,
    student: Student,
    client: Files,
) -> HomeworkAnswerFileResult:
    """Передаёт ограниченный multipart только как авторизованный ученик."""
    try:
        async with read_upload(request) as file:
            return await client.upload_file(
                student_id=student.id,
                homework_id=homework_id,
                answer_id=answer_id,
                file_id=file_id,
                stream=file.file,
                file_name=file.filename or "",
            )
    except HomeworkUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.get("/{homework_id}/answers/{answer_id}/files/{file_id}", response_model=None)
@router.head(
    "/{homework_id}/answers/{answer_id}/files/{file_id}",
    response_model=None,
    include_in_schema=False,
)
async def download_answer_file(
    homework_id: ID, answer_id: ID, file_id: ID, user: User, client: Files
) -> FileDownloadResponse:
    """Выдаёт приватный файл ученику-автору или назначенному преподавателю."""
    return FileDownloadResponse(client, user, homework_id, file_id, answer_id=answer_id)
