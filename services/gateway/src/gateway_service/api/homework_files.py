"""Публичное скачивание с JWT/актуальной ролью и доверенным запросом владельцу."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from gateway_service.api.file_download import FileDownloadResponse
from gateway_service.api.file_upload import read_upload
from gateway_service.api.homework import teacher_only
from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import HomeworkUnavailableError
from gateway_service.application.homework_files import HomeworkFileResult
from gateway_service.domain.user import Role
from gateway_service.infrastructure.homework_file_client import HomeworkFileClient

router = APIRouter(prefix="/api/v1/homework", tags=["homework"])
file_users = RequireRoles(allowed_roles=(Role.STUDENT, Role.TEACHER))


def get_homework_file_client(request: Request) -> HomeworkFileClient:
    """Возвращает файловый клиент либо503 при неполной настройке.

    Args:
        request: Запрос с ресурсами процесса.

    Returns:
        Клиент потокового доступа к Homework.

    Raises:
        HTTPException: Интеграция не настроена.
    """
    client = request.app.state.homework_file_client
    if client is None:
        raise HTTPException(503, "Service unavailable")
    return client


@router.put("/{homework_id}/files/{file_id}", response_model=HomeworkFileResult)
async def upload_homework_file(
    request: Request,
    homework_id: Annotated[int, Path(ge=1, le=2147483647)],
    file_id: Annotated[int, Path(ge=1, le=2147483647)],
    teacher: Annotated[GetCurrentUserResult, Depends(teacher_only)],
    client: Annotated[HomeworkFileClient, Depends(get_homework_file_client)],
) -> HomeworkFileResult:
    """Передаёт один ограниченный файл с UUID из авторизации, не из браузера.

    Args:
        request: Multipart с единственным полем file.
        homework_id: ID созданного задания.
        file_id: ID ожидаемого вложения.
        teacher: Активный преподаватель после проверки Gateway.
        client: Отдельный файловый клиент Homework.

    Returns:
        Публичные ready-метаданные, в том числе после безопасного повтора.

    Raises:
        HTTPException: Ошибка тела или неизвестный результат файловой операции.
        HomeworkRequestError: Известный отказ владельца без технических подробностей.
    """
    try:
        async with read_upload(request) as file:
            return await client.upload_file(
                teacher_id=teacher.id,
                homework_id=homework_id,
                file_id=file_id,
                stream=file.file,
                file_name=file.filename or "",
            )
    except HomeworkUnavailableError as exc:
        raise HTTPException(503, "Service unavailable") from exc


@router.get("/{homework_id}/files/{file_id}", response_model=None)
@router.head(
    "/{homework_id}/files/{file_id}", response_model=None, include_in_schema=False
)
async def get_homework_file(
    homework_id: Annotated[int, Path(ge=1, le=2147483647)],
    file_id: Annotated[int, Path(ge=1, le=2147483647)],
    user: Annotated[GetCurrentUserResult, Depends(file_users)],
    client: Annotated[HomeworkFileClient, Depends(get_homework_file_client)],
) -> FileDownloadResponse:
    """Передаёт только серверный UUID/роль, игнорируя их подмену браузером.

    Args:
        homework_id: ID задания из пути.
        file_id: ID вложения из пути.
        user: Пользователь после JWT и свежего чтения Gateway.
        client: Клиент владельца задания и файла.

    Returns:
        Потоковая выдача с перепроверкой доступа в Homework.
    """
    return FileDownloadResponse(client, user, homework_id, file_id)
