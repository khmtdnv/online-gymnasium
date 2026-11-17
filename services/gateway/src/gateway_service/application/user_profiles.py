"""Поиск пользователей и изменение ФИО без изменения учётных данных."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from gateway_service.application.errors import UserNotFoundError
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.domain.user import Role, User

NamePart = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, max_length=100)
]


class UserNames(BaseModel):
    """Обязательные имя и фамилия; отчество указывается только при наличии."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    first_name: NamePart = Field(min_length=1)
    last_name: NamePart = Field(min_length=1)
    middle_name: NamePart = ""


class UpdateUserNameCommand(UserNames):
    """Новое ФИО конкретного пользователя; имя и фамилия обязательны."""

    user_id: UUID
    first_name: NamePart = Field(min_length=1)
    last_name: NamePart = Field(min_length=1)


class SearchUsersQuery(BaseModel):
    """Ограниченный поиск; пустая строка не выгружает всех пользователей."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    q: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)
    ]
    role: Role | None = None
    active_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class UserProfile(UserNames):
    """Безопасный профиль без пароля и его хеша."""

    id: UUID
    email: str
    role: Role
    is_active: bool

    @classmethod
    def from_user(cls, user: User) -> UserProfile:
        """Копирует только разрешённые для ответа поля пользователя."""
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            first_name=user.first_name,
            last_name=user.last_name,
            middle_name=user.middle_name,
        )


class UserProfilesHandler:
    """Выполняет чтение и запись профилей через транзакции Gateway."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Сохраняет фабрику, не открывая сессию.

        Args:
            uow_factory: Фабрика отдельной транзакции Gateway.
        """
        self._uow_factory = uow_factory

    async def search(self, query: SearchUsersQuery) -> list[UserProfile]:
        """Возвращает ограниченную страницу совпадений в порядке репозитория.

        Args:
            query: Проверенные слова, фильтры и максимальное число результатов.

        Returns:
            Безопасные профили; пустой список, если совпадений нет.
        """
        async with self._uow_factory() as uow:
            users = await uow.users.search_users(
                query.q, query.role, query.active_only, query.limit
            )
            return [UserProfile.from_user(user) for user in users]

    async def get(self, user_id: UUID) -> UserProfile:
        """Читает профиль по идентификатору.

        Args:
            user_id: UUID пользователя Gateway.

        Returns:
            Профиль без хеша пароля.

        Raises:
            UserNotFoundError: Пользователь с этим ID отсутствует.
        """
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError
            return UserProfile.from_user(user)

    async def update_name(self, command: UpdateUserNameCommand) -> UserProfile:
        """Меняет только ФИО в отдельной транзакции.

        Args:
            command: ID и проверенные новые части имени.

        Returns:
            Профиль после изменения; commit выполняется при выходе из UoW.

        Raises:
            UserNotFoundError: Пользователь с этим ID отсутствует.
        """
        async with self._uow_factory() as uow:
            user = await uow.users.update_user_names(
                command.user_id,
                command.first_name,
                command.last_name,
                command.middle_name,
            )
            if user is None:
                raise UserNotFoundError
            return UserProfile.from_user(user)
