from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from gateway_service.application.errors import (
    InvalidParentStudentRolesError,
    UserNotFoundError,
)
from gateway_service.application.ports.password_service import PasswordService
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.application.user_profiles import UserNames
from gateway_service.domain.user import Role, User


class CreateUserCommand(UserNames):
    """Email, открытый пароль и роль нового пользователя."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    email: str
    password: str
    role: Role

    @field_validator("email", "password")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        """Отклоняет пустое значение, не обрезая пароль.

        Args:
            value: Проверенная строка email или пароля.

        Returns:
            Исходная непустая строка.

        Raises:
            ValueError: Значение состоит только из пробельных символов.
        """
        if not value.strip():
            raise ValueError("Email and password must not be blank")
        return value


class UserSummary(UserNames):
    """Публичные данные пользователя без пароля и его хеша."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: UUID
    email: str
    role: Role
    is_active: bool


class CreateUserHandler:
    """Создаёт пользователя с хешем пароля и возвращает безопасные данные."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        password_service: PasswordService,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            password_service: Сервис создания и проверки хешей паролей.
        """
        self._uow_factory = uow_factory
        self._password_service = password_service

    async def handle(self, command: CreateUserCommand) -> UserSummary:
        """Хеширует пароль и создаёт активного пользователя.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Данные нового пользователя без хеша пароля.

        Raises:
            EmailAlreadyExistsError: Email уже занят.
        """
        password_hash = self._password_service.hash(command.password)
        user = User(
            id=uuid4(),
            email=command.email,
            role=command.role,
            password_hash=password_hash,
            is_active=True,
            first_name=command.first_name,
            last_name=command.last_name,
            middle_name=command.middle_name,
        )
        async with self._uow_factory() as uow:
            await uow.users.create_user(user)
            await uow.outbox.add_user_event("gateway.user.created", user)

        return UserSummary(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            first_name=user.first_name,
            last_name=user.last_name,
            middle_name=user.middle_name,
        )


class ListUsersHandler:
    """Возвращает список пользователей без хешей паролей."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    async def handle(self) -> list[UserSummary]:
        """Читает список пользователей и исключает хеши паролей.

        Returns:
            Список безопасных описаний пользователей.
        """
        async with self._uow_factory() as uow:
            users = await uow.users.list_users()

        users_list = []
        for user in users:
            users_list.append(
                UserSummary(
                    id=user.id,
                    email=user.email,
                    role=user.role,
                    is_active=user.is_active,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    middle_name=user.middle_name,
                )
            )

        return users_list


class LinkParentStudentCommand(BaseModel):
    """ID родителя и ученика, между которыми нужно создать связь."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    parent_id: UUID
    student_id: UUID


class LinkParentStudentHandler:
    """Проверяет наличие и роли пользователей перед созданием связи."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: LinkParentStudentCommand) -> bool:
        """Проверяет роли и создаёт связь родителя с учеником.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            True для новой связи; False, если связь уже есть.

        Raises:
            UserNotFoundError: Родитель или ученик не найден.
            InvalidParentStudentRolesError: Роли пользователей не подходят для связи.
        """
        async with self._uow_factory() as uow:
            parent = await uow.users.get_by_id(command.parent_id)
            student = await uow.users.get_by_id(command.student_id)

            if parent is None or student is None:
                raise UserNotFoundError

            if parent.role is not Role.PARENT or student.role is not Role.STUDENT:
                raise InvalidParentStudentRolesError

            return await uow.users.create_parent_student_link(
                parent_id=parent.id,
                student_id=student.id,
            )
