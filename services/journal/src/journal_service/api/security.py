from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from journal_service.api.dependencies import ServicePrincipal, get_authenticated_service


class RequireServicePermission:
    """Проверяет одно требуемое право у распознанного сервиса."""

    def __init__(self, permission: str) -> None:
        """Запоминает право, необходимое для выполнения ручки.

        Args:
            permission: Имя требуемого права, например classes:write.
        """
        self._permission = permission

    def __call__(
        self, service: Annotated[ServicePrincipal, Depends(get_authenticated_service)]
    ) -> None:
        """Запрещает действие, если у сервиса нет требуемого права.

        Args:
            service: Сервис, уже распознанный зависимостью аутентификации.

        Raises:
            HTTPException: Сервис распознан, но нужного права у него нет.
        """
        if self._permission not in service.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient service permissions",
            )


def get_teacher_assignment_actor_id(
    service: Annotated[ServicePrincipal, Depends(get_authenticated_service)],
    x_actor_id: Annotated[str, Header(pattern=r"^[1-9][0-9]*$", max_length=19)],
) -> str:
    """Принимает сотрудника только от Backoffice с правом менять назначения.

    Args:
        service: Распознанный служебным токеном отправитель.
        x_actor_id: ID Django-сотрудника, назначенный Backoffice.

    Returns:
        Проверенный actor ID; он не берётся из тела запроса.

    Raises:
        HTTPException: Нет требуемых прав (403) или ID некорректен (422).
    """
    if (
        service.service_name != "backoffice"
        or "teacher-classes:write" not in service.permissions
    ):
        raise HTTPException(status_code=403, detail="Insufficient service permissions")
    if int(x_actor_id) > 9223372036854775807:
        raise HTTPException(status_code=422, detail="Invalid actor ID")
    return x_actor_id


def get_backoffice_actor_id(
    service: Annotated[ServicePrincipal, Depends(get_authenticated_service)],
    x_actor_id: Annotated[str, Header(pattern=r"^[1-9][0-9]*$", max_length=19)],
) -> str:
    """Принимает ID сотрудника только от Backoffice с правом записи периодов.

    Args:
        service: Уже распознанный сервис и его права.
        x_actor_id: Положительный десятичный ID Django-сотрудника.

    Returns:
        Проверенная строка ID без изменения её значения.

    Raises:
        HTTPException: Сервису запрещена запись либо ID превышает BIGINT.
    """
    if (
        service.service_name != "backoffice"
        or "class-periods:write" not in service.permissions
    ):
        raise HTTPException(status_code=403, detail="Insufficient service permissions")
    if int(x_actor_id) > 9223372036854775807:
        raise HTTPException(status_code=422, detail="Invalid actor ID")
    return x_actor_id
