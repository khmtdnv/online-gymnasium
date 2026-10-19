from pydantic import BaseModel, ConfigDict, Field

from schedule_service.application.errors import LessonNotFound, VersionConflict
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.events import LessonSnapshot, ScheduleChanged
from schedule_service.domain.lesson import Lesson


class CancelLessonCommand(BaseModel):
    """Данные отмены урока с ожидаемой версией."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    lesson_id: int = Field(gt=0)
    expected_version: int = Field(gt=0)


class CancelLessonHandler:
    """Отменяет урок с проверкой версии и записью событий."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: CancelLessonCommand) -> Lesson:
        """Отменяет урок и записывает события изменения расписания.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Отменённый урок с новой версией.

        Raises:
            LessonNotFound: Урок не найден.
            LessonAlreadyCanceled: Урок уже отменён.
            VersionConflict: Ожидаемая версия уже не актуальна.
        """
        async with self._uow_factory() as uow:
            lesson = await uow.lessons.get(lesson_id=command.lesson_id)

            if lesson is None:
                raise LessonNotFound

            lesson.cancel()

            canceled_lesson = await uow.lessons.cancel(
                lesson=lesson, expected_version=command.expected_version
            )
            if canceled_lesson is None:
                raise VersionConflict

            assert canceled_lesson.id is not None
            await uow.outbox.add(
                ScheduleChanged(
                    lesson_id=canceled_lesson.id,
                    class_id=canceled_lesson.class_id,
                    affected_dates=(canceled_lesson.starts_at.date(),),
                )
            )
            await uow.outbox.add(
                LessonSnapshot(
                    lesson_id=canceled_lesson.id,
                    class_id=canceled_lesson.class_id,
                    teacher_id=canceled_lesson.teacher_id,
                    subject_id=canceled_lesson.subject_id,
                    starts_at=canceled_lesson.starts_at,
                    ends_at=canceled_lesson.ends_at,
                    status=canceled_lesson.status,
                    version=canceled_lesson.version,
                )
            )

            return canceled_lesson
