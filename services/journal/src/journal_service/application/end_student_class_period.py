"""Завершение пребывания в классе без удаления истории или обращения к Gateway."""

from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from journal_service.application.class_periods import MAX_CLASS_ID
from journal_service.application.events import StudentClassPeriodEndedEvent
from journal_service.application.ports.errors import StudentClassPeriodConflictError
from journal_service.application.ports.unit_of_work import UnitOfWork


class EndStudentClassPeriodCommand(BaseModel):
    """Ожидаемый период ученика и доверенный контекст завершения."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    student_id: UUID
    expected_period_id: int = Field(ge=1, le=MAX_CLASS_ID)
    actor_id: str = Field(pattern="^[1-9][0-9]*$", max_length=19)
    request_id: str

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id(cls, value: str) -> str:
        """Проверяет верхнюю границу ID сотрудника.

        Args:
            value: Положительный десятичный ID из доверенного Backoffice.

        Returns:
            Исходный ID без преобразования.

        Raises:
            ValueError: ID не помещается в согласованный BIGINT.
        """
        if int(value) > 9223372036854775807:
            raise ValueError("Actor ID exceeds the allowed maximum")
        return value

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        """Проверяет строковый UUID запроса.

        Args:
            value: Идентификатор для корреляции запроса и события.

        Returns:
            Проверенная исходная строка.

        Raises:
            ValueError: Строка не представляет UUID.
        """
        UUID(value)
        return value


class EndStudentClassPeriodHandler:
    """Закрывает только ожидаемый период и сохраняет событие одной транзакцией."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет фабрику, не открывая транзакцию.

        Args:
            uow_factory: Общая транзакция закрытия периода и outbox.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: EndStudentClassPeriodCommand) -> None:
        """Завершает текущий период либо подтверждает отсутствие открытого.

        Args:
            command: Ожидаемый период ученика и контекст сотрудника.

        Raises:
            StudentClassPeriodConflictError: Открыт другой период или закрытие
                не выполнилось; устаревшая команда не изменяет новое состояние.
            SQLAlchemyError: Изменение или общий commit не удались.
        """
        async with self._uow_factory() as uow:
            period = await uow.class_periods.get_period_for_update(
                command.student_id, command.expected_period_id
            )
            if period is None or not period.is_active:
                current = await uow.class_periods.get_current_period_for_student(
                    command.student_id
                )
                if current is not None:
                    raise StudentClassPeriodConflictError
                return

            closed = await uow.class_periods.close_period(period.id)
            if closed is None:
                raise StudentClassPeriodConflictError
            await uow.outbox.add_event(
                StudentClassPeriodEndedEvent(
                    event_id=uuid4(),
                    occurred_at=closed.left_at,
                    request_id=command.request_id,
                    actor_id=command.actor_id,
                    student_id=closed.student_id,
                    period_id=closed.id,
                    class_id=closed.class_id,
                )
            )
