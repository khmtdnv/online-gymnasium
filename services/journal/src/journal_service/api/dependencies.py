import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from journal_service.application.add_student_to_class import AddStudentToClassHandler
from journal_service.application.class_periods import (
    GetCurrentPeriodForStudentHandler,
    ListCurrentPeriodsForClassHandler,
    ListPeriodsForStudentHandler,
)
from journal_service.application.classes import CreateClassHandler, ListClassesHandler
from journal_service.application.end_student_class_period import (
    EndStudentClassPeriodHandler,
)
from journal_service.application.teacher_classes import (
    AssignTeacherToClassHandler,
    ListClassesForTeacherHandler,
    UnassignTeacherFromClassHandler,
)
from journal_service.application.transfer_student_to_class import (
    TransferStudentToClassHandler,
)

bearer_scheme = HTTPBearer(auto_error=False)


class ServicePrincipal(BaseModel):
    """Хранит имя распознанного сервиса и неизменяемый набор его прав."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    service_name: str
    permissions: frozenset[str]


def get_authenticated_service(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> ServicePrincipal:
    """Распознаёт сервис по отдельному Bearer-токену и назначает его права.

    Args:
        request: Запрос с настройками Journal в состоянии приложения.
        credentials: Схема и токен, извлечённые из заголовка Authorization.

    Returns:
        Имя сервиса и назначенные ему права, без секретного токена.

    Raises:
        HTTPException: Credentials отсутствуют/неверны (401) или секреты
            разных сервисов совпадают и настройка неоднозначна (503).
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    incoming_token = credentials.credentials

    homework_token = request.app.state.settings.homework_service_token
    backoffice_token = request.app.state.settings.backoffice_service_token
    gateway_read_token = getattr(
        request.app.state.settings, "gateway_read_service_token", None
    )
    billing_read_token = getattr(
        request.app.state.settings, "billing_read_service_token", None
    )
    tokens = [
        value
        for value in (
            homework_token,
            backoffice_token,
            gateway_read_token,
            billing_read_token,
        )
        if value
    ]
    if len(set(tokens)) != len(tokens):
        raise HTTPException(status_code=503, detail="Service credentials misconfigured")
    if billing_read_token and secrets.compare_digest(
        incoming_token.encode(), billing_read_token.encode()
    ):
        return ServicePrincipal(
            service_name="billing", permissions=frozenset({"classes:read"})
        )
    if gateway_read_token and secrets.compare_digest(
        incoming_token.encode(), gateway_read_token.encode()
    ):
        return ServicePrincipal(
            service_name="gateway",
            permissions=frozenset({"classes:read", "student-current-class:read"}),
        )
    if homework_token and secrets.compare_digest(
        homework_token.encode(), backoffice_token.encode()
    ):
        raise HTTPException(status_code=503, detail="Service credentials misconfigured")
    if homework_token and secrets.compare_digest(
        incoming_token.encode(), homework_token.encode()
    ):
        return ServicePrincipal(
            service_name="homework",
            permissions=frozenset(
                {"teacher-classes:read", "student-current-class:read"}
            ),
        )

    if not secrets.compare_digest(
        incoming_token.encode("utf-8"),
        request.app.state.settings.backoffice_service_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return ServicePrincipal(
        service_name="backoffice",
        permissions=frozenset(
            {
                "classes:read",
                "classes:write",
                "class-periods:write",
                "teacher-classes:read",
                "teacher-classes:write",
                "student-current-class:read",
            }
        ),
    )


def get_assign_teacher_handler(request: Request) -> AssignTeacherToClassHandler:
    """Собирает назначение, запрещая его без авторитетной проверки Gateway.

    Args:
        request: Запрос с зависимостями приложения.

    Returns:
        Обработчик с reader и фабрикой UoW.

    Raises:
        HTTPException: Интеграция Gateway не настроена (503).
    """
    reader = request.app.state.gateway_user_reader
    if reader is None:
        raise HTTPException(status_code=503, detail="Gateway user lookup unavailable")
    return AssignTeacherToClassHandler(request.app.state.uow_factory, reader)


def get_unassign_teacher_handler(request: Request) -> UnassignTeacherFromClassHandler:
    """Собирает снятие назначения без Gateway.

    Args:
        request: Запрос с фабрикой UoW.

    Returns:
        Обработчик удаления связи.
    """
    return UnassignTeacherFromClassHandler(request.app.state.uow_factory)


def get_teacher_classes_handler(request: Request) -> ListClassesForTeacherHandler:
    """Собирает чтение назначенных классов.

    Args:
        request: Запрос с фабрикой UoW.

    Returns:
        Обработчик списка классов.
    """
    return ListClassesForTeacherHandler(request.app.state.uow_factory)


def get_create_class_handler(request: Request) -> CreateClassHandler:
    """Собирает обработчик создания класса из зависимостей приложения.

    Args:
        request: Запрос с фабрикой Unit of Work в состоянии приложения.

    Returns:
        Обработчик создания класса без открытия транзакции.
    """
    return CreateClassHandler(uow_factory=request.app.state.uow_factory)


def get_add_student_to_class_handler(request: Request) -> AddStudentToClassHandler:
    """Собирает добавление ученика, запрещая запись без проверки Gateway.

    Args:
        request: Запрос с фабрикой UoW и reader в состоянии приложения.

    Returns:
        Обработчик без открытия транзакции или HTTP-запроса.

    Raises:
        HTTPException: Интеграция Gateway не настроена.
    """
    reader = request.app.state.gateway_user_reader
    if reader is None:
        raise HTTPException(status_code=503, detail="Gateway user lookup unavailable")
    return AddStudentToClassHandler(request.app.state.uow_factory, reader)


def get_list_classes_handler(request: Request) -> ListClassesHandler:
    """Собирает обработчик списка классов из зависимостей приложения.

    Args:
        request: Запрос с фабрикой Unit of Work в состоянии приложения.

    Returns:
        Обработчик чтения классов без открытия транзакции.
    """
    return ListClassesHandler(uow_factory=request.app.state.uow_factory)


def get_transfer_student_to_class_handler(
    request: Request,
) -> TransferStudentToClassHandler:
    """Собирает перевод, запрещая его без настроенной проверки Gateway.

    Args:
        request: Запрос с фабрикой UoW и Gateway-reader.

    Returns:
        Обработчик перевода без открытия транзакции.

    Raises:
        HTTPException: Gateway-reader не настроен.
    """
    reader = request.app.state.gateway_user_reader
    if reader is None:
        raise HTTPException(status_code=503, detail="Gateway user lookup unavailable")
    return TransferStudentToClassHandler(request.app.state.uow_factory, reader)


def get_end_student_class_period_handler(
    request: Request,
) -> EndStudentClassPeriodHandler:
    """Собирает завершение без внешней проверки отключённого пользователя.

    Args:
        request: Запрос с фабрикой UoW.

    Returns:
        Обработчик завершения без открытия транзакции.
    """
    return EndStudentClassPeriodHandler(request.app.state.uow_factory)


def get_current_period_for_student_handler(
    request: Request,
) -> GetCurrentPeriodForStudentHandler:
    """Собирает обработчик текущего периода без открытия транзакции.

    Args:
        request: Запрос с фабрикой Unit of Work в app.state.

    Returns:
        Отдельный обработчик для текущего запроса.
    """
    return GetCurrentPeriodForStudentHandler(request.app.state.uow_factory)


def get_list_periods_for_student_handler(
    request: Request,
) -> ListPeriodsForStudentHandler:
    """Собирает обработчик истории ученика без открытия транзакции.

    Args:
        request: Запрос с фабрикой Unit of Work в app.state.

    Returns:
        Отдельный обработчик для текущего запроса.
    """
    return ListPeriodsForStudentHandler(request.app.state.uow_factory)


def get_list_current_periods_for_class_handler(
    request: Request,
) -> ListCurrentPeriodsForClassHandler:
    """Собирает обработчик состава класса без открытия транзакции.

    Args:
        request: Запрос с фабрикой Unit of Work в app.state.

    Returns:
        Отдельный обработчик для текущего запроса.
    """
    return ListCurrentPeriodsForClassHandler(request.app.state.uow_factory)
