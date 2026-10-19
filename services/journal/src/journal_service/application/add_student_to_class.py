"""Добавление активного ученика в класс без автоматического перевода."""

from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from journal_service.application.class_periods import ClassPeriodResult
from journal_service.application.events import StudentAddedToClassEvent
from journal_service.application.ports.errors import (
    ClassNotFoundError,
    CurrentPeriodAlreadyExistsError,
    InvalidStudentError,
    StudentClassConflictError,
    StudentNotFoundError,
)
from journal_service.application.ports.gateway_user_reader import GatewayUserReader
from journal_service.application.ports.unit_of_work import UnitOfWork
from journal_service.domain.student_class_period import StudentClassPeriod


class AddStudentToClassCommand(BaseModel):
    """Класс и ученик, а также доверенные данные инициатора и запроса."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    student_id: UUID = Field(strict=True)
    class_id: int = Field(strict=True, ge=1, le=2147483647)
    actor_id: str = Field(strict=True, pattern="^[1-9][0-9]*$", max_length=19)
    request_id: str = Field(strict=True)

    @field_validator("actor_id", mode="after")
    @classmethod
    def validate_actor_id(cls, value: str) -> str:
        """Проверяет верхнюю границу служебного ID после проверки формата.

        Args:
            value: Положительная десятичная строка без начальных нулей.

        Returns:
            Исходная строка ID.

        Raises:
            ValueError: ID превышает согласованный предел служебного контракта.
        """
        if int(value) > 9223372036854775807:
            raise ValueError("Actor ID exceeds the allowed maximum")
        return value

    @field_validator("request_id", mode="after")
    @classmethod
    def validate_request_id(cls, value: str) -> str:
        """Проверяет UUID в строке, не меняя тип поля.

        Args:
            value: Строковый идентификатор запроса.

        Returns:
            Исходная строка, если она разбирается как UUID.

        Raises:
            ValueError: Строка не представляет UUID.
        """
        UUID(value)
        return value


class AddStudentToClassResult(BaseModel):
    """Сохранённый период и признак создания для выбора HTTP-статуса."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    period: ClassPeriodResult
    created: bool


class AddStudentToClassHandler:
    """Добавляет активного ученика или возвращает его уже существующий период."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        user_reader: GatewayUserReader,
    ) -> None:
        """Сохраняет зависимости без открытия сессии или HTTP-запроса.

        Args:
            uow_factory: Фабрика общей транзакции периода и события.
            user_reader: Чтение пользователя из Gateway до записи в Journal.
        """
        self._uow_factory = uow_factory
        self._user_reader = user_reader

    async def handle(
        self, command: AddStudentToClassCommand
    ) -> AddStudentToClassResult:
        """Проверяет пользователя и создаёт либо возвращает открытый период.

        Gateway проверяется до открытия UoW. Повтор в тот же класс не создаёт
        новую запись и событие; другой текущий класс считается конфликтом.
        Новый период и событие сохраняются через один UoW.
        Типы и ограничения входных полей проверяет команда при создании.
        После конкурентного конфликта неудачный UoW завершается, а новый
        перечитывает период победителя: тот же класс даёт no-op, иной — конфликт.

        Args:
            command: Ученик, выбранный класс и данные инициатора запроса.

        Returns:
            Сохранённый период и created=True для новой записи либо False
            для существующей; вызывающий получает результат после выхода из UoW.

        Raises:
            StudentNotFoundError: Gateway подтвердил отсутствие пользователя.
            InvalidStudentError: Пользователь не активный ученик.
            UserLookupUnavailableError: Gateway не позволил проверить пользователя.
            ClassNotFoundError: Указанный класс отсутствует.
            StudentClassConflictError: Уже есть период в другом классе либо
                после конкурентной вставки текущий период больше не найден.
            SQLAlchemyError: Сохранение или завершение транзакции не удалось.
        """
        user = await self._user_reader.get_user(command.student_id)

        if user is None:
            raise StudentNotFoundError

        if not user.is_active or user.role != "student":
            raise InvalidStudentError
        try:
            async with self._uow_factory() as uow:
                school_class = await uow.classes.get_class_by_id(command.class_id)

                if school_class is None:
                    raise ClassNotFoundError

                current_period = await uow.class_periods.get_current_period_for_student(
                    command.student_id
                )

                if current_period is None:
                    new_period = StudentClassPeriod(
                        student_id=command.student_id,
                        class_id=command.class_id,
                    )
                    saved_period = await uow.class_periods.create_period(new_period)
                    event = StudentAddedToClassEvent(
                        event_id=uuid4(),
                        occurred_at=saved_period.joined_at,
                        request_id=command.request_id,
                        actor_id=command.actor_id,
                        student_id=command.student_id,
                        period_id=saved_period.id,
                        class_id=saved_period.class_id,
                    )
                    await uow.outbox.add_event(event)
                    return AddStudentToClassResult(
                        period=ClassPeriodResult.from_period(saved_period), created=True
                    )

                if current_period.class_id == command.class_id:
                    return AddStudentToClassResult(
                        period=ClassPeriodResult.from_period(current_period),
                        created=False,
                    )

                raise StudentClassConflictError
        except CurrentPeriodAlreadyExistsError:
            async with self._uow_factory() as uow:
                current_period = await uow.class_periods.get_current_period_for_student(
                    command.student_id
                )
                if (
                    current_period is not None
                    and current_period.class_id == command.class_id
                ):
                    return AddStudentToClassResult(
                        period=ClassPeriodResult.from_period(current_period),
                        created=False,
                    )

                raise StudentClassConflictError
