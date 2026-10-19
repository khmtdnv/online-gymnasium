from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from schedule_service.application.errors import LessonNotFound, VersionConflict
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.events import LessonSnapshot, ScheduleChanged
from schedule_service.domain.lesson import InvalidLessonInterval, Lesson


class UpdateLessonCommand(BaseModel):
    """Новый интервал урока и версия, которую ожидает клиент."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    lesson_id: int = Field(gt=0)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    expected_version: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Проверяет полный интервал урока до поиска записи в базе.

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


class UpdateLessonHandler:
    """Меняет интервал урока с проверкой версии и записью событий."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: UpdateLessonCommand) -> Lesson:
        """Переносит урок и записывает события для старого и нового дня.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Урок после изменения с новой версией.

        Raises:
            LessonNotFound: Урок не найден.
            VersionConflict: Ожидаемая версия уже не актуальна.
            InvalidLessonInterval: Новый интервал недопустим.
            ScheduleConflict: База отклонила новый интервал.
        """
        async with self._uow_factory() as uow:
            lesson = await uow.lessons.get(lesson_id=command.lesson_id)

            if lesson is None:
                raise LessonNotFound

            old_day = lesson.starts_at.date()

            lesson.reschedule(starts_at=command.starts_at, ends_at=command.ends_at)

            updated_lesson = await uow.lessons.update(
                lesson=lesson,
                expected_version=command.expected_version,
            )

            if updated_lesson is None:
                raise VersionConflict

            assert updated_lesson.id is not None
            await uow.outbox.add(
                ScheduleChanged(
                    lesson_id=updated_lesson.id,
                    class_id=updated_lesson.class_id,
                    affected_dates=tuple(
                        sorted({old_day, updated_lesson.starts_at.date()})
                    ),
                )
            )
            await uow.outbox.add(
                LessonSnapshot(
                    lesson_id=updated_lesson.id,
                    class_id=updated_lesson.class_id,
                    teacher_id=updated_lesson.teacher_id,
                    subject_id=updated_lesson.subject_id,
                    starts_at=updated_lesson.starts_at,
                    ends_at=updated_lesson.ends_at,
                    status=updated_lesson.status,
                    version=updated_lesson.version,
                )
            )

            return updated_lesson
