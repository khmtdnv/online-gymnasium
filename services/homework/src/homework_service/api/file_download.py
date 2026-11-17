"""Ограниченная потоковая выдача MinIO с владельцем соединения в ASGI-response."""

import logging
from urllib.parse import quote

from anyio import CancelScope, CapacityLimiter, to_thread
from starlette.responses import Response, StreamingResponse
from starlette.types import Receive, Scope, Send

from homework_service.api.errors import unavailable
from homework_service.application.ports.file_storage import FileStorage
from homework_service.domain.homework_answer_file import HomeworkAnswerFile
from homework_service.domain.homework_file import HomeworkFile

logger = logging.getLogger(__name__)


class FileDownloadResponse(StreamingResponse):
    """Открывает объект после допуска и закрывает даже при отмене ASGI-запроса."""

    def __init__(
        self,
        file: HomeworkFile | HomeworkAnswerFile,
        storage: FileStorage,
        limiter: CapacityLimiter,
    ) -> None:
        """Готовит безопасные заголовки, не открывая MinIO заранее.

        Args:
            file: Готовое вложение после свежей проверки доступа.
            storage: Приватное хранилище с синхронным чтением.
            limiter: Общий предел одновременно открытых скачиваний процесса.
        """
        self._file = file
        self._storage = storage
        self._limiter = limiter
        super().__init__(
            content=[],
            headers={
                "Content-Type": file.content_type,
                "Content-Length": str(file.size_bytes),
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(file.file_name, safe=""),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Владеет ресурсом дольше генератора и закрывает его в shielded finally.

        Args:
            scope: ASGI-контекст GET либо HEAD.
            receive: Получение отключения клиента на старых версиях ASGI.
            send: Передача заголовков и ограниченных блоков байтов.

        Raises:
            HomeworkHTTPError: Открытие или первое чтение не выполнено, HTTP503.
            OSError: Чтение после заголовков нарушено; поток обрывается без JSON.
        """
        async with self._limiter:
            context = None
            stream = None
            entered = False
            remaining = self._file.size_bytes

            async def read_chunk() -> bytes:
                nonlocal remaining
                if remaining == 0:
                    return b""
                try:
                    chunk = await to_thread.run_sync(
                        stream.read, min(65536, remaining + 1)
                    )
                    if (
                        not isinstance(chunk, bytes)
                        or not chunk
                        or len(chunk) > remaining
                    ):
                        raise OSError("Unexpected file length")
                    remaining -= len(chunk)
                    if remaining == 0 and await to_thread.run_sync(stream.read, 1):
                        raise OSError("Unexpected file length")
                    return chunk
                except Exception as exc:
                    # Только граница чтения внешнего потока: наружу не выходят
                    # исключения SDK, адрес bucket и технические детали.
                    raise OSError("File read unavailable") from exc

            try:
                try:
                    with CancelScope(shield=True):
                        context = await to_thread.run_sync(
                            self._storage.open, self._file.storage_key
                        )
                        stream = await to_thread.run_sync(context.__enter__)
                        entered = True
                    if scope["method"] != "HEAD":
                        first = await read_chunk()
                except Exception as exc:
                    raise unavailable() from exc

                if scope["method"] == "HEAD":
                    await Response(headers=dict(self.headers))(scope, receive, send)
                    return

                async def chunks():
                    yield first
                    while chunk := await read_chunk():
                        yield chunk

                self.body_iterator = chunks()
                await super().__call__(scope, receive, send)
            finally:
                if entered:
                    with CancelScope(shield=True):
                        try:
                            await to_thread.run_sync(context.__exit__, None, None, None)
                        except OSError:
                            logger.warning("Homework file stream cleanup failed")
