"""Потоковая выдача Gateway с обязательным закрытием ответа Homework."""

from urllib.parse import quote

from fastapi import HTTPException
from starlette.responses import Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.homework import (
    HomeworkUnavailableError,
)
from gateway_service.infrastructure.homework_file_client import HomeworkFileClient


class FileDownloadResponse(StreamingResponse):
    """Держит ответ Homework открытым до завершения или отмены отправки браузеру."""

    def __init__(
        self,
        client: HomeworkFileClient,
        user: GetCurrentUserResult,
        homework_id: int,
        file_id: int,
        *,
        answer_id: int | None = None,
    ) -> None:
        """Сохраняет доверенный контекст без исходящего HTTP-запроса.

        Args:
            client: Отдельный потоковый клиент Homework.
            user: Активный пользователь с проверенной ролью.
            homework_id: ID задания.
            file_id: ID вложения.
            answer_id: ID попытки для приватного ученического файла.
        """
        self._client = client
        self._user = user
        self._homework_id = homework_id
        self._file_id = file_id
        self._answer_id = answer_id
        super().__init__(content=[])

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Проверяет заголовки до ответа и закрывает upstream в контексте клиента.

        Args:
            scope: ASGI-контекст GET/HEAD.
            receive: Получение отключения клиента.
            send: Отправка проверенных заголовков и ограниченных блоков.

        Raises:
            HTTPException: Известный отказ владельца или недоступность до headers.
            HomeworkUnavailableError: Поток нарушен после headers, без второго JSON.
        """
        started = False

        async def send_message(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with self._client.download_file(
                user_id=self._user.id,
                role=self._user.role.value,
                homework_id=self._homework_id,
                file_id=self._file_id,
                **(
                    {"answer_id": self._answer_id}
                    if self._answer_id is not None
                    else {}
                ),
            ) as (file, response):
                headers = {
                    "Content-Type": file.content_type,
                    "Content-Length": str(file.size_bytes),
                    "Content-Disposition": "attachment; filename*=UTF-8''"
                    + quote(file.file_name, safe=""),
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                }
                self.init_headers(headers)
                if scope["method"] == "HEAD":
                    await Response(headers=headers)(scope, receive, send_message)
                    return
                iterator = response.aiter_bytes(chunk_size=65536).__aiter__()
                remaining = file.size_bytes

                async def read_chunk():
                    nonlocal remaining
                    if remaining == 0:
                        return b""
                    chunk = await anext(iterator, b"")
                    if not chunk or len(chunk) > remaining:
                        raise HomeworkUnavailableError
                    remaining -= len(chunk)
                    if remaining == 0 and await anext(iterator, b""):
                        raise HomeworkUnavailableError
                    return chunk

                first = await read_chunk()

                async def chunks():
                    yield first
                    while chunk := await read_chunk():
                        yield chunk

                self.body_iterator = chunks()
                # Исключения после headers не преобразуем во второй JSON-ответ.
                await super().__call__(scope, receive, send_message)
        except HomeworkUnavailableError as exc:
            if started:
                raise
            raise HTTPException(503, "Service unavailable") from exc
