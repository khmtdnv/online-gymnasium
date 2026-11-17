"""Сдача, чтение истории и однократная проверка ученических работ."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from homework_service.application.homework import PositiveId
from homework_service.application.homework_files import HomeworkFileInput
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkAnswerConflictError,
    HomeworkAnswerNotFoundError,
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.application.ports.journal_reader import JournalReader
from homework_service.application.ports.schedule_reader import ScheduleReader
from homework_service.application.ports.unit_of_work import UnitOfWork
from homework_service.domain.homework import Homework
from homework_service.domain.homework_answer import HomeworkAnswer
from homework_service.domain.homework_answer_file import HomeworkAnswerFile

Text = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, max_length=10000)
]


class HomeworkAnswerFileResult(BaseModel):
    """Публичный файл попытки, без приватного ключа и отпечатка."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    id: PositiveId
    answer_id: PositiveId
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=10485760)
    content_type: str = Field(min_length=1, max_length=127)
    upload_status: Literal["pending", "ready"]

    @classmethod
    def from_file(cls, file: HomeworkAnswerFile) -> Self:
        """Отбирает только публичные метаданные своей попытки."""
        return cls(**{field: getattr(file, field) for field in cls.model_fields})


class HomeworkAnswerResult(BaseModel):
    """Попытка с историческим результатом; ключ повтора не раскрывается."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: PositiveId
    homework_id: PositiveId
    student_id: UUID
    attempt_number: PositiveId
    answer_text: Text
    status: Literal["submitted", "returned", "graded"]
    submitted_at: AwareDatetime
    grade: int | None = Field(default=None, strict=True, ge=2, le=5)
    teacher_comment: Text = ""
    reviewer_id: UUID | None = None
    reviewed_at: AwareDatetime | None = None
    files: list[HomeworkAnswerFileResult] = Field(default_factory=list, max_length=5)

    @classmethod
    def from_answer(
        cls, answer: HomeworkAnswer, files: list[HomeworkAnswerFile]
    ) -> Self:
        """Собирает результат после сохранения без полей идемпотентности."""
        return cls(
            **{
                key: value
                for key, value in asdict(answer).items()
                if key not in ("idempotency_key", "request_hash")
            },
            files=[HomeworkAnswerFileResult.from_file(file) for file in files],
        )


class HomeworkAnswerInput(BaseModel):
    """Только пользовательское содержимое, без подмены автора и серверных полей."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    answer_text: Text = ""
    files: list[HomeworkFileInput] = Field(
        default_factory=list, max_length=5, strict=True
    )

    @model_validator(mode="after")
    def validate_answer(self) -> Self:
        """Не допускает сдачу без текста и без ожидаемого файла."""
        if not self.answer_text and not self.files:
            raise ValueError("An answer or a file is required")
        return self


class SubmitHomeworkAnswerCommand(HomeworkAnswerInput):
    """Содержимое ответа с автором Gateway и стабильным ключом отправки."""

    student_id: UUID
    homework_id: PositiveId
    idempotency_key: str = Field(strict=True, pattern=r"^[!-~]{1,128}$")


class SubmitHomeworkAnswerResult(BaseModel):
    """Отличает новую попытку201 от безопасного повтора200."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    answer: HomeworkAnswerResult
    created: bool


class HomeworkAnswerReviewInput(BaseModel):
    """Результат проверки без возможности выбрать чужой UUID преподавателя."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["returned", "graded"]
    grade: int | None = Field(default=None, strict=True, ge=2, le=5)
    teacher_comment: Text = ""

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        """Отделяет оценку от возврата с обязательным комментарием."""
        if (
            self.status == "graded"
            and self.grade is None
            or self.status == "returned"
            and (self.grade is not None or not self.teacher_comment)
        ):
            raise ValueError("Invalid grade or return comment")
        return self


class ReviewHomeworkAnswerCommand(HomeworkAnswerReviewInput):
    """Решение с доверенным UUID преподавателя и адресом конкретной попытки."""

    teacher_id: UUID
    homework_id: PositiveId
    answer_id: PositiveId


class HomeworkAnswersQuery(BaseModel):
    """Контекст пользователя и ограниченная страница разрешённых работ."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: UUID
    role: Literal["student", "teacher"]
    homework_id: PositiveId
    answer_id: PositiveId | None = None
    student_id: UUID | None = None
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    offset: int = Field(default=0, strict=True, ge=0, le=2147483647)


class HomeworkAnswerAccess:
    """Проверяет владельцев до локальной записи, не держит SQL во время HTTP."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        journal_reader: JournalReader,
        schedule_reader: ScheduleReader,
    ) -> None:
        """Сохраняет фабрику транзакций и авторитетные readers."""
        self._uow_factory = uow_factory
        self._journal_reader = journal_reader
        self._schedule_reader = schedule_reader

    async def authorize(self, user_id: UUID, role: str, homework_id: int) -> Homework:
        """Разрешает текущему ученику класса или назначенному учителю своего урока.

        Args:
            user_id: UUID, проверенный Gateway.
            role: Доверенная актуальная роль.
            homework_id: Задание, к которому относятся работы.

        Returns:
            Доступное задание, отделённое от сессии.

        Raises:
            HomeworkNotFoundError: Задание отсутствует или не в текущем классе.
            HomeworkAccessDeniedError: Преподаватель больше не имеет права.
            OwnerLookupUnavailableError: Нельзя подтвердить актуальные ссылки.
        """
        async with self._uow_factory() as uow:
            parent = await uow.homeworks.get_by_id(homework_id)
        if parent is None:
            raise HomeworkNotFoundError
        if role == "student":
            if (
                await self._journal_reader.get_current_class_id(user_id)
                != parent.class_id
            ):
                raise HomeworkNotFoundError
        elif role == "teacher":
            if not await self._journal_reader.is_teacher_assigned(
                user_id, parent.class_id
            ):
                raise HomeworkAccessDeniedError
            ids = sorted(
                {
                    parent.issued_lesson_id,
                    *(() if parent.due_lesson_id is None else (parent.due_lesson_id,)),
                }
            )
            lessons = await self._schedule_reader.get_lessons(ids)
            for id in ids:
                lesson = lessons.get(id)
                if (
                    lesson is None
                    or lesson.id != id
                    or lesson.class_id != parent.class_id
                    or lesson.subject_id != parent.subject_id
                ):
                    raise OwnerLookupUnavailableError("Incompatible answer lesson")
            if not any(lessons[id].teacher_id == user_id for id in ids):
                raise HomeworkAccessDeniedError
        else:
            raise HomeworkAccessDeniedError
        return parent

    @staticmethod
    async def result(uow: UnitOfWork, answer: HomeworkAnswer) -> HomeworkAnswerResult:
        """Дополняет один ответ его собственными вложениями."""
        files = await uow.answer_files.list_for_answers([answer.id])
        return HomeworkAnswerResult.from_answer(answer, files.get(answer.id, []))


class SubmitHomeworkAnswerHandler(HomeworkAnswerAccess):
    """Создаёт новую попытку либо возвращает результат той же отправки."""

    async def handle(
        self, command: SubmitHomeworkAnswerCommand
    ) -> SubmitHomeworkAnswerResult:
        """Сохраняет ответ и файлы одной транзакцией, не повторяет неизвестную запись.

        Args:
            command: Проверенный ученик, ответ и стабильный ключ отправки.

        Returns:
            Попытка после commit и признак её создания.

        Raises:
            HomeworkAnswerConflictError: Ключ изменил данные или предыдущая работа не возвращена.
            HomeworkNotFoundError: Нет доступа к этому заданию.
        """
        await self.authorize(command.student_id, "student", command.homework_id)
        fingerprint = hashlib.sha256(
            json.dumps(
                command.model_dump(mode="json", exclude={"idempotency_key"}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        try:
            async with self._uow_factory() as uow:
                previous = await uow.answers.get_by_key(
                    command.homework_id, command.student_id, command.idempotency_key
                )
                if previous is not None:
                    if previous.request_hash != fingerprint:
                        raise HomeworkAnswerConflictError
                    result = await self.result(uow, previous)
                    created = False
                else:
                    latest = await uow.answers.get_latest(
                        command.homework_id, command.student_id
                    )
                    if latest is not None and latest.status != "returned":
                        raise HomeworkAnswerConflictError
                    answer = await uow.answers.add(
                        HomeworkAnswer(
                            homework_id=command.homework_id,
                            student_id=command.student_id,
                            answer_text=command.answer_text,
                            idempotency_key=command.idempotency_key,
                            request_hash=fingerprint,
                            attempt_number=1
                            if latest is None
                            else latest.attempt_number + 1,
                        )
                    )
                    files = (
                        await uow.answer_files.add_files(answer.id, command.files)
                        if command.files
                        else []
                    )
                    result = HomeworkAnswerResult.from_answer(answer, files)
                    created = True
        except HomeworkAnswerConflictError:
            async with self._uow_factory() as uow:
                previous = await uow.answers.get_by_key(
                    command.homework_id, command.student_id, command.idempotency_key
                )
                if previous is None or previous.request_hash != fingerprint:
                    raise HomeworkAnswerConflictError from None
                result = await self.result(uow, previous)
                created = False
        return SubmitHomeworkAnswerResult(answer=result, created=created)


class ReviewHomeworkAnswerHandler(HomeworkAnswerAccess):
    """Однократно оценивает работу или возвращает её ученику."""

    async def handle(
        self, command: ReviewHomeworkAnswerCommand
    ) -> HomeworkAnswerResult:
        """Блокирует ответ в том же порядке, что и финализация его вложений.

        Args:
            command: Преподаватель, попытка и проверенное решение.

        Returns:
            Сохранённая проверка, включая повтор того же решения.

        Raises:
            HomeworkAnswerNotFoundError: Ответ не относится к указанному заданию.
            HomeworkAnswerConflictError: Иная проверка уже сохранена либо файлы не готовы.
        """
        homework = await self.authorize(
            command.teacher_id, "teacher", command.homework_id
        )
        async with self._uow_factory() as uow:
            answer = await uow.answers.get_by_id(command.answer_id, for_update=True)
            if answer is None or answer.homework_id != command.homework_id:
                raise HomeworkAnswerNotFoundError
            if answer.status != "submitted":
                if (
                    answer.status,
                    answer.grade,
                    answer.teacher_comment,
                    answer.reviewer_id,
                ) != (
                    command.status,
                    command.grade,
                    command.teacher_comment,
                    command.teacher_id,
                ):
                    raise HomeworkAnswerConflictError
            else:
                if command.status == "graded" and await uow.answer_files.has_pending(
                    answer.id
                ):
                    raise HomeworkAnswerConflictError
                (
                    answer.status,
                    answer.grade,
                    answer.teacher_comment,
                    answer.reviewer_id,
                ) = (
                    command.status,
                    command.grade,
                    command.teacher_comment,
                    command.teacher_id,
                )
                answer.reviewed_at = await uow.files.get_current_time()
                answer.__post_init__()
                answer = await uow.answers.save_review(answer)
                await uow.outbox.add_review_event(homework, answer)
            result = await self.result(uow, answer)
        return result


class ReadHomeworkAnswersHandler(HomeworkAnswerAccess):
    """Читает собственную историю ученика или разрешённые работы преподавателя."""

    async def handle(self, query: HomeworkAnswersQuery) -> list[HomeworkAnswerResult]:
        """Возвращает страницу либо одну конкретную разрешённую попытку.

        Args:
            query: Доверенный пользователь, задание, ID либо фильтр страницы.

        Returns:
            Ответы с файлами одной пакетной выборки.

        Raises:
            HomeworkAnswerNotFoundError: Прямая ссылка указывает на чужой ответ.
            HomeworkAccessDeniedError: Ученик попытался задать чужой фильтр.
        """
        await self.authorize(query.user_id, query.role, query.homework_id)
        if query.role == "student" and query.student_id is not None:
            raise HomeworkAccessDeniedError
        async with self._uow_factory() as uow:
            if query.answer_id is not None:
                answer = await uow.answers.get_by_id(query.answer_id)
                if (
                    answer is None
                    or answer.homework_id != query.homework_id
                    or query.role == "student"
                    and answer.student_id != query.user_id
                ):
                    raise HomeworkAnswerNotFoundError
                answers = [answer]
            else:
                answers = await uow.answers.list_answers(
                    query.homework_id,
                    query.user_id if query.role == "student" else query.student_id,
                    query.limit,
                    query.offset,
                    latest_only=query.role == "teacher" and query.student_id is None,
                )
            files = await uow.answer_files.list_for_answers(
                [answer.id for answer in answers]
            )
            results = [
                HomeworkAnswerResult.from_answer(answer, files.get(answer.id, []))
                for answer in answers
            ]
        return results
