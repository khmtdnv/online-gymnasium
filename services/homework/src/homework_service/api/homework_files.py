"""Закрытое скачивание: служебный доступ, свежие права и только готовые байты."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import require_gateway
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.api.file_download import FileDownloadResponse
from homework_service.api.file_upload import read_upload
from homework_service.application.homework_files import (
    GetHomeworkFileHandler,
    GetHomeworkFileQuery,
    HomeworkFileResult,
    UploadHomeworkFileCommand,
    UploadHomeworkFileHandler,
)
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkFileNotReadyError,
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)

router = APIRouter(
    prefix="/internal/homework",
    include_in_schema=False,
    dependencies=[Depends(require_gateway)],
)


def get_upload_homework_file_handler(request: Request) -> UploadHomeworkFileHandler:
    """Возвращает собранную загрузку либо503 без файловой интеграции.

    Args:
        request: Запрос с ресурсами процесса.

    Returns:
        Обработчик проверки прав, сохранения и фиксации вложения.

    Raises:
        HomeworkHTTPError: Загрузка не настроена.
    """
    handler = request.app.state.upload_homework_file_handler
    if handler is None:
        raise unavailable()
    return handler


@router.put("/{homework_id}/files/{file_id}", response_model=HomeworkFileResult)
async def upload_homework_file(
    request: Request,
    homework_id: Annotated[int, Path(ge=1, le=2147483647)],
    file_id: Annotated[int, Path(ge=1, le=2147483647)],
    teacher_id: Annotated[UUID, Header(alias="X-Teacher-ID")],
    handler: Annotated[
        UploadHomeworkFileHandler, Depends(get_upload_homework_file_handler)
    ],
) -> HomeworkFileResult:
    """Принимает один ограниченный файл и сохраняет неизменяемую готовую версию.

    Args:
        request: Multipart с единственной частью file.
        homework_id: ID ранее созданного задания.
        file_id: ID ожидаемого вложения этого задания.
        teacher_id: Проверенный Gateway преподаватель.
        handler: Сценарий с актуальными правами и безопасным повтором.

    Returns:
        Готовые публичные метаданные; повтор также возвращает200.

    Raises:
        HomeworkHTTPError: Нет прав/вложения, неверное содержимое либо сбой зависимости.
        HTTPException: Тело превышает лимиты или нарушает multipart-контракт.
    """
    try:
        async with read_upload(request) as file:
            return await handler.handle(
                UploadHomeworkFileCommand(
                    teacher_id=teacher_id, homework_id=homework_id, file_id=file_id
                ),
                file.file,
            )
    except HomeworkNotFoundError as exc:
        raise HomeworkHTTPError(
            404, "homework_not_found", "Homework not found"
        ) from exc
    except HomeworkAccessDeniedError as exc:
        raise HomeworkHTTPError(403, "access_denied", "Access denied") from exc
    except ValueError as exc:
        raise HomeworkHTTPError(
            422, "invalid_homework_file", "Invalid homework file"
        ) from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc


def get_homework_file_handler(request: Request) -> GetHomeworkFileHandler:
    """Возвращает собранный сценарий либо закрывает ненастроенное чтение.

    Args:
        request: Запрос с ресурсами приложения.

    Returns:
        Обработчик проверки текущего доступа.

    Raises:
        HomeworkHTTPError: Зависимости не настроены, HTTP503.
    """
    handler = request.app.state.get_homework_file_handler
    if handler is None:
        raise unavailable()
    return handler


@router.api_route(
    "/{homework_id}/files/{file_id}", methods=["GET", "HEAD"], response_model=None
)
async def get_homework_file(
    request: Request,
    homework_id: Annotated[int, Path(ge=1, le=2147483647)],
    file_id: Annotated[int, Path(ge=1, le=2147483647)],
    user_id: Annotated[UUID, Header(alias="X-User-ID")],
    role: Annotated[Literal["student", "teacher"], Header(alias="X-User-Role")],
    handler: Annotated[GetHomeworkFileHandler, Depends(get_homework_file_handler)],
) -> FileDownloadResponse:
    """Передаёт объект потоку только после проверки доверенного пользователя.

    Args:
        request: GET/HEAD с ресурсами процесса.
        homework_id: ID задания из пути.
        file_id: ID вложения из пути.
        user_id: UUID, установленный Gateway.
        role: Актуальная роль из Gateway, не query/body клиента.
        handler: Сценарий проверки связи, класса и уроков.

    Returns:
        Поток с безопасными заголовками, без публичного ключа объекта.

    Raises:
        HomeworkHTTPError: Нет доступа/файла, pending либо зависимость недоступна.
    """
    try:
        file = await handler.handle(
            GetHomeworkFileQuery(
                user_id=user_id, role=role, homework_id=homework_id, file_id=file_id
            )
        )
    except HomeworkNotFoundError as exc:
        raise HomeworkHTTPError(
            404, "homework_not_found", "Homework not found"
        ) from exc
    except HomeworkAccessDeniedError as exc:
        raise HomeworkHTTPError(403, "access_denied", "Access denied") from exc
    except HomeworkFileNotReadyError as exc:
        raise HomeworkHTTPError(
            409, "homework_file_not_ready", "Homework file not ready"
        ) from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc
    storage = request.app.state.file_storage
    if storage is None:
        raise unavailable()
    return FileDownloadResponse(file, storage, request.app.state.file_download_limiter)
