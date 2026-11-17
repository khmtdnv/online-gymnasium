"""Приватные ученические файлы: отдельный путь и доступ к конкретной попытке."""

from fastapi import APIRouter, Depends, Request

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.api.file_download import FileDownloadResponse
from homework_service.api.file_upload import read_upload
from homework_service.api.homework_answers import (
    ID,
    UserID,
    UserRole,
    answer_errors,
    answer_handler,
)
from homework_service.application.homework_answers import HomeworkAnswerFileResult

router = APIRouter(
    prefix="/internal/homework",
    include_in_schema=False,
    dependencies=[Depends(require_gateway)],
)


@router.put(
    "/{homework_id}/answers/{answer_id}/files/{file_id}",
    response_model=HomeworkAnswerFileResult,
)
async def upload_answer_file(
    request: Request,
    homework_id: ID,
    answer_id: ID,
    file_id: ID,
    user_id: UserID,
    role: UserRole,
) -> HomeworkAnswerFileResult:
    """Догружает только собственную ещё не закрытую попытку ученика."""
    if role != "student":
        raise HomeworkHTTPError(403, "access_denied", "Access denied")
    handler = answer_handler(request, "homework_answer_files_handler")
    with answer_errors():
        async with read_upload(request) as file:
            return await handler.upload(
                user_id, homework_id, answer_id, file_id, file.file
            )


@router.api_route(
    "/{homework_id}/answers/{answer_id}/files/{file_id}",
    methods=["GET", "HEAD"],
    response_model=None,
)
async def download_answer_file(
    request: Request,
    homework_id: ID,
    answer_id: ID,
    file_id: ID,
    user_id: UserID,
    role: UserRole,
) -> FileDownloadResponse:
    """Повторно проверяет автора/преподавателя перед открытием приватных байтов."""
    with answer_errors():
        file = await answer_handler(request, "homework_answer_files_handler").get_file(
            user_id, role, homework_id, answer_id, file_id
        )
    storage = request.app.state.file_storage
    if storage is None:
        raise unavailable()
    return FileDownloadResponse(file, storage, request.app.state.file_download_limiter)
