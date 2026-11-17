"""Файлы ученика: свежий доступ, передача вне SQL и фиксация до проверки работы."""

import logging
from collections.abc import Callable
from secrets import token_hex
from typing import BinaryIO
from uuid import UUID

from anyio import CapacityLimiter, to_thread

from homework_service.application.homework_answers import (
    HomeworkAnswerAccess,
    HomeworkAnswerFileResult,
)
from homework_service.application.homework_files import HomeworkFileInput
from homework_service.application.ports.errors import (
    HomeworkAnswerConflictError,
    HomeworkAnswerNotFoundError,
    HomeworkFileNotReadyError,
)
from homework_service.application.ports.file_storage import FileStorage
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.application.ports.unit_of_work import UnitOfWork
from homework_service.domain.homework_answer_file import HomeworkAnswerFile

logger = logging.getLogger(__name__)


class HomeworkAnswerFilesHandler(HomeworkAnswerAccess):
    """Использует готовые parser/validator/storage, не выдаёт ответы всему классу."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal_reader: JournalReader,
        schedule_reader: ScheduleReader,
        storage: FileStorage | None = None,
        limiter: CapacityLimiter | None = None,
    ) -> None:
        """Сохраняет зависимости, не открывая транзакцию или соединение MinIO.

        Args:
            uow_factory: Фабрика коротких транзакций собственной БД.
            journal_reader: Текущий класс ученика и назначения преподавателя.
            schedule_reader: Авторитетные уроки выдачи и срока.
            storage: Приватный bucket; без него загрузка недоступна.
            limiter: Общий предел одновременно проверяемых и загружаемых файлов.
        """
        super().__init__(uow_factory, journal_reader, schedule_reader)
        self._storage = storage
        self._limiter = limiter

    async def get_file(
        self, user_id: UUID, role: str, homework_id: int, answer_id: int, file_id: int
    ) -> HomeworkAnswerFile:
        """Разрешает чтение только автору ответа или преподавателю задания.

        Args:
            user_id: UUID активного пользователя Gateway.
            role: Проверенная роль student/teacher.
            homework_id: Задание, доступ которого перепроверяется.
            answer_id: Попытка ответа, не произвольный parent.
            file_id: Файл именно этой попытки.

        Returns:
            Разрешённый готовый файл с приватным ключом только для транспорта.

        Raises:
            HomeworkAnswerNotFoundError: Чужая попытка или несовпадающая связь.
            HomeworkFileNotReadyError: Файл ещё не загружен.
        """
        await self.authorize(user_id, role, homework_id)
        async with self._uow_factory() as uow:
            answer = await uow.answers.get_by_id(answer_id)
            file = await uow.answer_files.get_by_id(file_id)
            if (
                answer is None
                or answer.homework_id != homework_id
                or role == "student"
                and answer.student_id != user_id
                or file is None
                or file.answer_id != answer_id
                or file.homework_id != homework_id
            ):
                raise HomeworkAnswerNotFoundError
        if file.upload_status != "ready":
            raise HomeworkFileNotReadyError
        return file

    async def upload(
        self,
        student_id: UUID,
        homework_id: int,
        answer_id: int,
        file_id: int,
        stream: BinaryIO,
    ) -> HomeworkAnswerFileResult:
        """Догружает ожидаемый файл; закрытая проверкой попытка больше не изменяется.

        Args:
            student_id: Автор из Gateway, не поле формы.
            homework_id: ID доступного задания.
            answer_id: ID собственной попытки.
            file_id: ID её ожидаемого файла.
            stream: Seekable multipart, закрываемый HTTP-слоем.

        Returns:
            Ready-метаданные после подтверждённого commit.

        Raises:
            HomeworkAnswerNotFoundError: Ответ или файл чужие/отсутствуют.
            HomeworkAnswerConflictError: Попытка уже проверена или возвращена.
            ValueError: Байты не соответствуют исходным метаданным.
            OSError: Неизвестный результат хранилища или истёкшая попытка загрузки.
        """
        await self.authorize(student_id, "student", homework_id)
        async with self._uow_factory() as uow:
            answer = await uow.answers.get_by_id(answer_id)
            file = await uow.answer_files.get_by_id(file_id)
            if (
                answer is None
                or answer.homework_id != homework_id
                or answer.student_id != student_id
                or file is None
                or file.answer_id != answer_id
                or file.homework_id != homework_id
            ):
                raise HomeworkAnswerNotFoundError
            if file.upload_status == "ready":
                return HomeworkAnswerFileResult.from_file(file)
            if answer.status != "submitted":
                raise HomeworkAnswerConflictError
            started_at = await uow.files.get_current_time()
        if self._storage is None:
            raise OSError("File storage unavailable")
        from homework_service.infrastructure.file_validation import validate_file

        expected = HomeworkFileInput(
            file_name=file.file_name,
            size_bytes=file.size_bytes,
            content_type=file.content_type,
            content_sha256=file.content_sha256,
        )
        key = f"homework/{homework_id}/answers/{answer_id}/files/{file_id}/{token_hex(16)}"

        def write() -> None:
            content_type = validate_file(stream, expected)
            self._storage.put(key, stream, file.size_bytes, content_type)

        await to_thread.run_sync(write, limiter=self._limiter)
        try:
            async with self._uow_factory() as uow:
                locked = await uow.answers.get_by_id(answer_id, for_update=True)
                saved = await uow.answer_files.get_by_id(file_id)
                if (
                    locked is None
                    or locked.student_id != student_id
                    or locked.homework_id != homework_id
                    or saved is None
                    or saved.answer_id != answer_id
                ):
                    raise HomeworkAnswerNotFoundError
                if saved.upload_status != "ready":
                    if locked.status != "submitted":
                        raise HomeworkAnswerConflictError
                    saved = await uow.answer_files.mark_ready(file_id, key, started_at)
                    if saved is None:
                        raise OSError("File upload attempt expired")
        except Exception:
            # Сбой commit не доказывает rollback: подтверждаем связь в новой сессии.
            async with self._uow_factory() as uow:
                saved = await uow.answer_files.get_by_id(file_id)
            if (
                saved is None
                or saved.answer_id != answer_id
                or saved.homework_id != homework_id
                or saved.upload_status != "ready"
            ):
                raise
        if saved.storage_key != key:
            try:
                await to_thread.run_sync(self._storage.delete, key)
            except OSError:
                logger.warning("Unused answer file cleanup deferred")
        return HomeworkAnswerFileResult.from_file(saved)
