"""Проверенные описания ожидаемых файлов и безопасные результаты приложения."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, BinaryIO, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkFileNotReadyError,
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.domain.homework import Homework
from homework_service.domain.homework_file import HomeworkFile

if TYPE_CHECKING:
    from homework_service.application.ports.unit_of_work import UnitOfWork


class HomeworkFileInput(BaseModel):
    """Описание выбранного файла, но не подтверждение получения его байтов."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    file_name: str
    size_bytes: int
    content_type: str
    content_sha256: str

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """Применяет одинаковые локальные правила к API и другим входам приложения.

        Returns:
            Проверенное описание.

        Raises:
            ValueError: Недопустимое имя, формат, размер или отпечаток.
        """
        HomeworkFile.validate_metadata(
            self.file_name, self.size_bytes, self.content_type, self.content_sha256
        )
        return self


class HomeworkFileResult(BaseModel):
    """Публичные метаданные без приватного адреса объекта и отпечатка содержимого."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: int = Field(ge=1, le=2147483647)
    homework_id: int = Field(ge=1, le=2147483647)
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=10485760)
    content_type: str = Field(min_length=1, max_length=127)
    upload_status: Literal["pending", "ready"]

    @classmethod
    def from_file(cls, file: HomeworkFile) -> Self:
        """Отбирает только публичные поля сохранённого вложения.

        Args:
            file: Доменное вложение с ID после flush/commit.

        Returns:
            Метаданные для клиента.

        Raises:
            ValueError: Вложение ещё не сохранено либо имеет неверные поля.
        """
        return cls.model_validate(
            {
                "id": file.id,
                "homework_id": file.homework_id,
                "file_name": file.file_name,
                "size_bytes": file.size_bytes,
                "content_type": file.content_type,
                "upload_status": file.upload_status,
            }
        )


class UploadHomeworkFileCommand(BaseModel):
    """Доверенный преподаватель и конкретное ожидаемое вложение задания."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    teacher_id: UUID
    homework_id: int = Field(strict=True, ge=1, le=2147483647)
    file_id: int = Field(strict=True, ge=1, le=2147483647)


class UploadHomeworkFileHandler:
    """Связывает проверку прав, загрузку байтов и безопасную фиксацию готовности."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        check_teacher_access: Callable[[UUID, Homework], Awaitable[None]],
        save_file: Callable[[HomeworkFile, BinaryIO], Awaitable[tuple[str, datetime]]],
        finish_upload: Callable[
            [HomeworkFile, str, datetime], Awaitable[HomeworkFileResult]
        ],
    ) -> None:
        """Сохраняет готовые зависимости, не читая БД и не загружая файл.

        Args:
            uow_factory: Отдельная транзакция чтения задания и вложения.
            check_teacher_access: Свежая проверка урока и назначения преподавателя.
            save_file: Проверка байтов и загрузка в MinIO вне транзакции.
            finish_upload: Условная фиксация готовности и восстановление после гонки.
        """
        self._uow_factory = uow_factory
        self._check_teacher_access = check_teacher_access
        self._save_file = save_file
        self._finish_upload = finish_upload

    async def handle(
        self, command: UploadHomeworkFileCommand, stream: BinaryIO
    ) -> HomeworkFileResult:
        """Проверяет доступ и возвращает готовое либо загружает ожидаемое вложение.

        Args:
            command: Доверенный учитель и ID задания/вложения.
            stream: Seekable-поток multipart; его закрывает HTTP-слой.

        Returns:
            Метаданные уже готового либо только что загруженного вложения.

        Raises:
            HomeworkNotFoundError: Задание/вложение отсутствует либо связь не совпала.
            HomeworkAccessDeniedError: Нет текущего права на исходный урок или класс.
            OwnerLookupUnavailableError: Проверка владельцев не выполнена.
            ValueError: Байты не соответствуют ожидаемому вложению.
            OSError: Файл не сохранён либо результат не удалось подтвердить.
        """
        async with self._uow_factory() as uow:
            homework = await uow.homeworks.get_by_id(command.homework_id)

            if homework is None:
                raise HomeworkNotFoundError

            file = await uow.files.get_by_id(command.file_id)

            if file is None or file.homework_id != command.homework_id:
                raise HomeworkNotFoundError

        await self._check_teacher_access(command.teacher_id, homework)

        if file.upload_status == "ready":
            return HomeworkFileResult.from_file(file)
        else:
            storage_key, started_at = await self._save_file(file, stream)
            return await self._finish_upload(file, storage_key, started_at)


class GetHomeworkFileQuery(BaseModel):
    """Файл задания и доверенные UUID/роль из аутентифицированного Gateway."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    role: Literal["student", "teacher"]
    homework_id: int = Field(strict=True, ge=1, le=2147483647)
    file_id: int = Field(strict=True, ge=1, le=2147483647)


class GetHomeworkFileHandler:
    """Разрешает скачивание только по текущим данным Journal и Schedule."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal_reader: JournalReader,
        schedule_reader: ScheduleReader,
    ) -> None:
        """Сохраняет зависимости без открытия БД или объекта.

        Args:
            uow_factory: Короткая транзакция чтения метаданных.
            journal_reader: Текущий класс ученика и назначения преподавателя.
            schedule_reader: Владельцы исходного урока и урока срока.
        """
        self._uow_factory = uow_factory
        self._journal_reader = journal_reader
        self._schedule_reader = schedule_reader

    async def handle(self, query: GetHomeworkFileQuery) -> HomeworkFile:
        """Проверяет связь и свежий доступ до выдачи внутреннего ключа потоку.

        Args:
            query: Доверенный пользователь и точные ID задания/вложения.

        Returns:
            Готовое вложение с приватным ключом только для HTTP-транспорта.
            Этот результат нельзя сериализовать в публичный JSON.

        Raises:
            HomeworkNotFoundError: Нет задания/файла, чужая связь или класс ученика.
            HomeworkAccessDeniedError: Нет назначения либо собственного урока.
            HomeworkFileNotReadyError: Доступ есть, но файл ещё pending.
            OwnerLookupUnavailableError: Владелец недоступен или ссылки испорчены.
        """
        async with self._uow_factory() as uow:
            homework = await uow.homeworks.get_by_id(query.homework_id)
            if homework is None:
                raise HomeworkNotFoundError
            file = await uow.files.get_by_id(query.file_id)
            if file is None or file.homework_id != homework.id:
                raise HomeworkNotFoundError

        if query.role == "student":
            class_id = await self._journal_reader.get_current_class_id(query.user_id)
            if class_id != homework.class_id:
                raise HomeworkNotFoundError
        else:
            if not await self._journal_reader.is_teacher_assigned(
                query.user_id, homework.class_id
            ):
                raise HomeworkAccessDeniedError
            ids = [homework.issued_lesson_id]
            if homework.due_lesson_id is not None:
                ids.append(homework.due_lesson_id)
            lessons = await self._schedule_reader.get_lessons(ids)
            if set(lessons) != set(ids) or any(
                lesson.id != id
                or lesson.class_id != homework.class_id
                or lesson.subject_id != homework.subject_id
                for id, lesson in lessons.items()
            ):
                raise OwnerLookupUnavailableError("Incompatible homework lesson")
            if not any(
                lesson.teacher_id == query.user_id for lesson in lessons.values()
            ):
                raise HomeworkAccessDeniedError
        if file.upload_status != "ready":
            raise HomeworkFileNotReadyError
        return file
