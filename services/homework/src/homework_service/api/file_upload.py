"""Один multipart-файл с ограниченными телом, временем чтения и памятью spool."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from anyio import CancelScope, fail_after
from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser


class _UploadParser(MultiPartParser):
    """Проверяет конечную границу и закрывает незавершённые spool-файлы."""

    is_complete: bool = False

    def on_end(self) -> None:
        """Отмечает получение закрывающей границы multipart."""
        self.is_complete = True

    def close(self) -> None:
        """Закрывает также частичный файл, которого ещё нет в FormData.

        Starlette 1.7 хранит его в _files_to_close_on_error. Зависимость от этого
        внутреннего списка изолирована здесь и защищена тестом оборванного тела:
        python-multipart 0.0.32 не проверяет конечную границу в finalize().
        """
        for file in self._files_to_close_on_error:
            if not file.closed:
                file.close()


@asynccontextmanager
async def read_upload(request: Request) -> AsyncIterator[UploadFile]:
    """Разбирает одно вложение и закрывает его при любом исходе обработки.

    Args:
        request: Запрос после проверки служебного токена или пользовательских прав.

    Yields:
        Один seekable UploadFile размером от 1 байта до 10 МиБ.

    Raises:
        HTTPException: Неверный формат/структура, превышение размера или времени.
    """
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "multipart/form-data"
    ):
        raise HTTPException(415, "Expected multipart/form-data")

    async def limited_stream() -> AsyncIterator[bytes]:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 11 * 1024 * 1024:
                raise HTTPException(413, "Upload body too large")
            yield chunk

    form = None
    parser = None
    try:
        try:
            with fail_after(300):
                parser = _UploadParser(
                    request.headers,
                    limited_stream(),
                    max_files=1,
                    max_fields=0,
                    max_part_size=10485760,
                )
                form = await parser.parse()
        except MultiPartException as exc:
            raise HTTPException(422, "Invalid multipart file") from exc
        except TimeoutError as exc:
            raise HTTPException(408, "Upload body timed out") from exc
        if not parser.is_complete:
            raise HTTPException(422, "Incomplete multipart file")
        items = form.multi_items()
        if (
            len(items) != 1
            or items[0][0] != "file"
            or not isinstance(items[0][1], UploadFile)
        ):
            raise HTTPException(422, "Expected one file field")
        upload = items[0][1]
        if upload.size is None or upload.size < 1:
            raise HTTPException(422, "Empty file is not allowed")
        if upload.size > 10485760:
            raise HTTPException(413, "File too large")
        yield upload
    finally:
        with CancelScope(shield=True):
            try:
                if form is not None:
                    await form.close()
            finally:
                if parser is not None:
                    parser.close()
