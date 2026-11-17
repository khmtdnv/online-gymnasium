"""Перевод ученика с сохранением истории и события в одной транзакции."""

from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from journal_service.application.class_periods import MAX_CLASS_ID, ClassPeriodResult
from journal_service.application.events import StudentTransferredToClassEvent
from journal_service.application.ports.errors import (
    ClassNotFoundError,
    InvalidStudentError,
    StudentClassPeriodConflictError,
    StudentNotFoundError,
)
from journal_service.application.ports.gateway_user_reader import GatewayUserReader
from journal_service.application.ports.unit_of_work import UnitOfWork
from journal_service.domain.student_class_period import StudentClassPeriod


class TransferStudentToClassCommand(BaseModel):
    """Целевой класс, ожидаемый исходный период и доверенный контекст действия."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    student_id: UUID
    target_class_id: int = Field(ge=1, le=MAX_CLASS_ID)
    expected_period_id: int = Field(ge=1, le=MAX_CLASS_ID)
    actor_id: str = Field(pattern="^[1-9][0-9]*$", max_length=19)
    request_id: str

    @field_validator("actor_id")
    @classmethod
    def validate_actor_id(cls, value: str) -> str:
        """Ограничивает положительный служебный ID диапазоном BIGINT.

        Args:
            value: Десятичный ID сотрудника из доверенного Backoffice.

        Returns:
            Проверенная исходная строка.

        Raises:
            ValueError: ID превышает согласованную верхнюю границу.
        """
        if int(value) > 9223372036854775807:
            raise ValueError("Actor ID exceeds the allowed maximum")
        return value

    @field_validator("request_id")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        """Проверяет строковый UUID запроса, не меняя представление.

        Args:
            value: Идентификатор запроса для корреляции и события.

        Returns:
            Строка, разбираемая как UUID.

        Raises:
            ValueError: Значение не представляет UUID.
        """
        UUID(value)
        return value


class TransferStudentToClassHandler:
    """Переводит ученика только из того периода, который видел сотрудник."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        user_reader: GatewayUserReader,
    ) -> None:
        """Сохраняет зависимости без HTTP-запроса и открытия транзакции.

        Args:
            uow_factory: Общая транзакция закрытия, вступления и события.
            user_reader: Проверка пользователя у владельца учётных записей.
        """
        self._uow_factory = uow_factory
        self._user_reader = user_reader

    async def handle(self, command: TransferStudentToClassCommand) -> ClassPeriodResult:
        """Проверяет ученика и переводит его из ожидаемого открытого периода.

        Gateway проверяется до UoW. Исходный период читается под блокировкой;
        устаревшее ожидание не позволяет изменить новый текущий период.
        Закрытие, вступление с общей датой и событие выполняются одной транзакцией.
        Тот же целевой класс при совпавшем открытом периоде не создаёт записей.

        Args:
            command: Ученик, целевой класс, ожидаемый период и контекст действия.

        Returns:
            Новый период либо исходный при отсутствии изменения класса.

        Raises:
            StudentNotFoundError: Gateway подтвердил отсутствие пользователя.
            InvalidStudentError: Пользователь не является активным учеником.
            UserLookupUnavailableError: Проверка пользователя недоступна.
            ClassNotFoundError: Целевой класс отсутствует.
            StudentClassPeriodConflictError: Исходный период устарел или не найден.
            SQLAlchemyError: Запись или завершение общей транзакции не удалось.
        """
        user = await self._user_reader.get_user(command.student_id)

        if user is None:
            raise StudentNotFoundError

        if not user.is_active or user.role != "student":
            raise InvalidStudentError

        async with self._uow_factory() as uow:
            target_class = await uow.classes.get_class_by_id(command.target_class_id)

            if target_class is None:
                raise ClassNotFoundError

            previous_period = await uow.class_periods.get_period_for_update(
                command.student_id, command.expected_period_id
            )

            if previous_period is None or previous_period.left_at is not None:
                raise StudentClassPeriodConflictError

            if previous_period.class_id == command.target_class_id:
                return ClassPeriodResult.from_period(previous_period)

            previous_period = await uow.class_periods.close_period(previous_period.id)

            if previous_period is None:
                raise StudentClassPeriodConflictError

            new_period = await uow.class_periods.create_period(
                StudentClassPeriod(
                    student_id=command.student_id,
                    class_id=command.target_class_id,
                    joined_at=previous_period.left_at,
                )
            )

            await uow.outbox.add_event(
                StudentTransferredToClassEvent(
                    event_id=uuid4(),
                    occurred_at=new_period.joined_at,
                    request_id=command.request_id,
                    actor_id=command.actor_id,
                    student_id=new_period.student_id,
                    previous_period_id=previous_period.id,
                    previous_class_id=previous_period.class_id,
                    period_id=new_period.id,
                    class_id=new_period.class_id,
                )
            )

            return ClassPeriodResult.from_period(new_period)
