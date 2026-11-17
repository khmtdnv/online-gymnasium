from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from schedule_service.application.errors import (
    IdempotencyKeyAlreadyExists,
    IdempotencyKeyReuse,
)
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.events import LessonSnapshot, ScheduleChanged
from schedule_service.domain.lesson import InvalidLessonInterval, Lesson


class CreateLessonCommand(BaseModel):
    """Данные для создания урока и проверки повторного запроса."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    class_id: int = Field(gt=0)
    teacher_id: UUID
    subject_id: int = Field(gt=0)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    idempotency_key: str | None = None
    request_hash: str | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Проверяет полный интервал урока до открытия UoW.

        Returns:
            Команда с допустимым интервалом.

        Raises:
            ValueError: Начало не предшествует окончанию или даты различаются.
        """
        try:
            Lesson._validate_interval(self.starts_at, self.ends_at)
        except InvalidLessonInterval as exc:
            raise ValueError("Invalid lesson interval") from exc
        return self


class CreateLessonHandler:
    """Создаёт урок, события и запись повторного запроса в одной транзакции."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: CreateLessonCommand) -> Lesson:
        """Создаёт урок и два события либо возвращает урок повторного запроса.

        Урок, outbox и ключ запроса записываются в одной транзакции. При повторе
        write-UoW сначала откатывается и закрывается, затем новый UoW читает
        результат победителя без повторного создания урока и событий.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Созданный или найденный при повторе урок.

        Raises:
            InvalidLessonInterval: Интервал урока недопустим.
            ScheduleConflict: База отклонила запись урока.
            IdempotencyKeyReuse: Ключ уже использован для других данных.
            RuntimeError: У занятого ключа отсутствует завершённый результат.
        """
        lesson = Lesson.create(
            class_id=command.class_id,
            teacher_id=command.teacher_id,
            subject_id=command.subject_id,
            starts_at=command.starts_at,
            ends_at=command.ends_at,
        )
        try:
            async with self._uow_factory() as uow:
                if command.idempotency_key is not None:
                    assert command.request_hash is not None
                    await uow.idempotency.claim(
                        "create_lesson", command.idempotency_key, command.request_hash
                    )

                db_lesson = await uow.lessons.add(lesson)
                assert db_lesson.id is not None

                await uow.outbox.add(
                    ScheduleChanged(
                        lesson_id=db_lesson.id,
                        class_id=db_lesson.class_id,
                        affected_dates=(db_lesson.starts_at.date(),),
                    )
                )
                await uow.outbox.add(
                    LessonSnapshot(
                        lesson_id=db_lesson.id,
                        class_id=db_lesson.class_id,
                        teacher_id=db_lesson.teacher_id,
                        subject_id=db_lesson.subject_id,
                        starts_at=db_lesson.starts_at,
                        ends_at=db_lesson.ends_at,
                        status=db_lesson.status,
                        version=db_lesson.version,
                    )
                )

                if command.idempotency_key is not None:
                    await uow.idempotency.complete(
                        "create_lesson", command.idempotency_key, db_lesson
                    )
                return db_lesson

        except IdempotencyKeyAlreadyExists:
            if command.idempotency_key is None:
                raise
            async with self._uow_factory() as uow:
                record = await uow.idempotency.get_by_key(
                    "create_lesson", command.idempotency_key
                )
                if record is None:
                    raise RuntimeError("Idempotency result is unavailable")
                if record.request_hash != command.request_hash:
                    raise IdempotencyKeyReuse
                if record.lesson is None:
                    raise RuntimeError("Idempotency result has no completed lesson")
                return record.lesson
