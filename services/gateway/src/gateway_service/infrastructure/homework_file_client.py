"""Отдельный потоковый клиент файлов, не меняющий таймауты JSON-запросов."""

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import token_hex
from typing import BinaryIO, Literal
from urllib.parse import quote, unquote
from uuid import UUID

import httpx
from anyio import CancelScope, to_thread
from pydantic import ValidationError

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.application.homework_answers import HomeworkAnswerFileResult
from gateway_service.application.homework_files import HomeworkFileResult


class HomeworkFileClient:
    """Владеет одним ответом внутри контекста и не передаёт сырые заголовки."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Сохраняет отдельный HTTP-клиент и credentials Gateway→Homework.

        Args:
            http_client: Клиент с файловыми таймаутами, закрываемый lifespan.
            service_token: Служебный Bearer, не пользовательский JWT.

        Raises:
            ValueError: Пустой служебный токен.
        """
        if not service_token:
            raise ValueError("Homework service token is required")
        self._http_client = http_client
        self._service_token = service_token

    async def upload_file(
        self,
        *,
        teacher_id: UUID | None = None,
        student_id: UUID | None = None,
        homework_id: int,
        file_id: int,
        stream: BinaryIO,
        file_name: str,
        answer_id: int | None = None,
    ) -> HomeworkFileResult | HomeworkAnswerFileResult:
        """Передаёт один spool порциями, не повторяя запись при неизвестном результате.

        Args:
            teacher_id: UUID преподавателя из авторизации Gateway.
            student_id: UUID автора ученического файла вместо teacher_id.
            homework_id: ID задания из проверенного пути.
            file_id: ID ожидаемого вложения.
            stream: Ограниченный seekable-файл, закрываемый HTTP-ручкой.
            file_name: Имя выбранного файла для сверки ответа владельца.
            answer_id: ID попытки для ученического файла.

        Returns:
            Проверенные ready-метаданные именно этого вложения.

        Raises:
            HomeworkRequestError: Известный безопасный отказ владельца.
            HomeworkUnavailableError: Неизвестный результат записи или нарушенный контракт.
        """
        actor_id = teacher_id if answer_id is None else student_id
        if actor_id is None or (teacher_id is not None and student_id is not None):
            raise ValueError("Choose the matching upload author")
        boundary = token_hex(24)
        size = 0

        async def chunks() -> AsyncIterator[bytes]:
            nonlocal size
            yield (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{quote(file_name, safe="")}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode("ascii")
            await to_thread.run_sync(stream.seek, 0)
            while chunk := await to_thread.run_sync(stream.read, 65536):
                size += len(chunk)
                if size > 10485760:
                    raise HomeworkUnavailableError
                yield chunk
            yield f"\r\n--{boundary}--\r\n".encode("ascii")

        response = None
        try:
            request = self._http_client.build_request(
                "PUT",
                f"/internal/homework/{homework_id}"
                + (f"/answers/{answer_id}" if answer_id is not None else "")
                + f"/files/{file_id}",
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    **(
                        {"X-Teacher-ID": str(actor_id)}
                        if answer_id is None
                        else {"X-User-ID": str(actor_id), "X-User-Role": "student"}
                    ),
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Accept-Encoding": "identity",
                },
                content=chunks(),
            )
            response = await self._http_client.send(
                request, stream=True, follow_redirects=False
            )
            if response.headers.get("content-encoding", "identity") != "identity":
                raise HomeworkUnavailableError
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                body.extend(chunk)
                if len(body) > 8192:
                    raise HomeworkUnavailableError
            if response.status_code != 200:
                try:
                    code = json.loads(body)["error"]["code"]
                except (ValueError, KeyError, TypeError) as exc:
                    raise HomeworkUnavailableError from exc
                if (response.status_code, code) in (
                    (403, "access_denied"),
                    (404, "homework_not_found"),
                    (422, "invalid_homework_file"),
                    (404, "homework_answer_not_found"),
                    (409, "homework_answer_conflict"),
                    (422, "invalid_homework_answer"),
                ):
                    raise HomeworkRequestError(response.status_code, code)
                raise HomeworkUnavailableError
            result = (
                HomeworkFileResult if answer_id is None else HomeworkAnswerFileResult
            ).model_validate_json(body)
            if (
                result.id != file_id
                or (
                    result.homework_id != homework_id
                    if answer_id is None
                    else result.answer_id != answer_id
                )
                or result.upload_status != "ready"
                or result.file_name != file_name
                or result.size_bytes != size
            ):
                raise HomeworkUnavailableError
            return result
        except (httpx.HTTPError, OSError, ValidationError) as exc:
            raise HomeworkUnavailableError from exc
        finally:
            if response is not None:
                with CancelScope(shield=True):
                    await response.aclose()

    @asynccontextmanager
    async def download_file(
        self,
        *,
        user_id: UUID,
        role: Literal["student", "teacher"],
        homework_id: int,
        file_id: int,
        answer_id: int | None = None,
    ) -> AsyncIterator[
        tuple[HomeworkFileResult | HomeworkAnswerFileResult, httpx.Response]
    ]:
        """Открывает GET после проверки Gateway; возвращает проверенные заголовки.

        Args:
            user_id: UUID активного пользователя из Gateway.
            role: Его текущая роль, не заголовок браузера.
            homework_id: ID задания из проверенного пути.
            file_id: ID вложения из проверенного пути.
            answer_id: Необязательный ID попытки для отдельного приватного пути.

        Yields:
            Публичные метаданные и поток, действующий только внутри контекста.

        Raises:
            HomeworkRequestError: Известный отказ403/404 либо файл ещё pending409.
            HomeworkUnavailableError: Сбой сети, статуса, заголовков или тела.
        """
        response = None
        try:
            request = self._http_client.build_request(
                "GET",
                f"/internal/homework/{homework_id}"
                + (f"/answers/{answer_id}" if answer_id is not None else "")
                + f"/files/{file_id}",
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "X-User-ID": str(user_id),
                    "X-User-Role": role,
                    "Accept-Encoding": "identity",
                },
            )
            with CancelScope(shield=True):
                response = await self._http_client.send(
                    request, stream=True, follow_redirects=False
                )
            if response.status_code != 200:
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    body.extend(chunk)
                    if len(body) > 8192:
                        raise HomeworkUnavailableError
                try:
                    payload = json.loads(body)
                    code = payload["error"]["code"]
                except ValueError, KeyError, TypeError:
                    raise HomeworkUnavailableError from None
                if (response.status_code, code) in (
                    (403, "access_denied"),
                    (404, "homework_not_found"),
                    (409, "homework_file_not_ready"),
                    (404, "homework_answer_not_found"),
                ):
                    raise HomeworkRequestError(response.status_code, code)
                raise HomeworkUnavailableError
            try:
                length = response.headers["content-length"]
                disposition = response.headers["content-disposition"]
                prefix = "attachment; filename*=UTF-8''"
                if (
                    not length.isascii()
                    or not length.isdecimal()
                    or not disposition.startswith(prefix)
                    or re.search(r"%(?![0-9a-fA-F]{2})", disposition[len(prefix) :])
                    or response.headers.get("content-encoding", "identity")
                    != "identity"
                ):
                    raise ValueError("Invalid download headers")
                file = (
                    HomeworkFileResult
                    if answer_id is None
                    else HomeworkAnswerFileResult
                )(
                    id=file_id,
                    **(
                        {"homework_id": homework_id}
                        if answer_id is None
                        else {"answer_id": answer_id}
                    ),
                    file_name=unquote(
                        disposition[len(prefix) :], encoding="utf-8", errors="strict"
                    ),
                    size_bytes=int(length),
                    content_type=response.headers["content-type"],
                    upload_status="ready",
                )
            except (KeyError, ValueError, ValidationError) as exc:
                raise HomeworkUnavailableError from exc
            yield file, response
        except httpx.HTTPError as exc:
            raise HomeworkUnavailableError from exc
        finally:
            if response is not None:
                with CancelScope(shield=True):
                    await response.aclose()
