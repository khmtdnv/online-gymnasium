from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from gateway_service.application.errors import AuthenticationError
from gateway_service.application.ports.password_service import PasswordService
from gateway_service.application.ports.token_service import TokenService
from gateway_service.application.ports.unit_of_work import UnitOfWork
from gateway_service.domain.user import Role


class RefreshCommand(BaseModel):
    """Refresh-токен, который нужно заменить новой парой токенов."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    refresh_token: str


class RefreshResult(BaseModel):
    """Пара access- и refresh-токенов для текущего пользователя."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    access_token: str
    refresh_token: str


class RefreshHandler:
    """Заменяет одноразовый refresh-токен и выдаёт новую пару токенов."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            token_service: Сервис проверки и выпуска JWT.
        """
        self._uow_factory = uow_factory
        self._token_service = token_service

    async def handle(self, command: RefreshCommand) -> RefreshResult:
        """Заменяет refresh-токен новой парой в одной транзакции.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Новые access- и refresh-токены.

        Raises:
            AuthenticationError: Токен непригоден либо пользователь отсутствует или
                неактивен.
        """
        decoded_refresh = self._token_service.decode_refresh(command.refresh_token)

        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(user_id=decoded_refresh.user_id)
            if user is None or not user.is_active:
                raise AuthenticationError

            if (
                decoded_refresh.session_id is not None
                and not await uow.auth_sessions.is_active(
                    decoded_refresh.session_id, decoded_refresh.user_id
                )
            ):
                raise AuthenticationError

            consumed = await uow.users.consume_refresh_token(
                token_id=decoded_refresh.jti,
                user_id=decoded_refresh.user_id,
            )
            if not consumed:
                raise AuthenticationError

            session_id = decoded_refresh.session_id or uuid4()
            issued_refresh = self._token_service.issue_refresh(
                user, session_id=session_id
            )
            access_token = self._token_service.issue_access(user, session_id=session_id)
            if decoded_refresh.session_id is None:
                await uow.auth_sessions.create(
                    session_id, user.id, issued_refresh.expires_at
                )
            await uow.users.create_refresh_token(
                token_id=issued_refresh.jti,
                user_id=decoded_refresh.user_id,
                expires_at=issued_refresh.expires_at,
            )

            return RefreshResult(
                access_token=access_token,
                refresh_token=issued_refresh.token,
            )


class LoginCommand(BaseModel):
    """Email и открытый пароль для проверки входа."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    email: str
    password: str
    previous_refresh_token: str | None = Field(default=None, repr=False)


class LoginResult(BaseModel):
    """Пара access- и refresh-токенов для текущего пользователя."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    access_token: str
    refresh_token: str


class LoginHandler:
    """Проверяет вход и создаёт серверную сессию и refresh-токен."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        password_service: PasswordService,
        token_service: TokenService,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            password_service: Сервис создания и проверки хешей паролей.
            token_service: Сервис проверки и выпуска JWT.
        """
        self._uow_factory = uow_factory
        self._password_service = password_service
        self._token_service = token_service

    async def handle(self, command: LoginCommand) -> LoginResult:
        """Проверяет пароль и записывает новый refresh-токен.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Access- и refresh-токены пользователя.

        Raises:
            AuthenticationError: Неверные учётные данные или неактивный пользователь.
        """
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(command.email)

            if user is None or not user.is_active:
                raise AuthenticationError

            if not self._password_service.verify(command.password, user.password_hash):
                raise AuthenticationError

            if command.previous_refresh_token:
                try:
                    previous = self._token_service.decode_refresh(
                        command.previous_refresh_token
                    )
                except AuthenticationError:
                    previous = None
                if previous is not None:
                    await uow.users.consume_refresh_token(
                        previous.jti, previous.user_id
                    )
                    if previous.session_id is not None:
                        await uow.auth_sessions.revoke(
                            previous.session_id, previous.user_id
                        )

            session_id = uuid4()
            access_token = self._token_service.issue_access(user, session_id=session_id)
            issued_refresh = self._token_service.issue_refresh(
                user, session_id=session_id
            )

            await uow.auth_sessions.create(
                session_id, user.id, issued_refresh.expires_at
            )

            await uow.users.create_refresh_token(
                token_id=issued_refresh.jti,
                user_id=user.id,
                expires_at=issued_refresh.expires_at,
            )
            await uow.outbox.add_user_event("gateway.user.logged_in", user)

            return LoginResult(
                access_token=access_token,
                refresh_token=issued_refresh.token,
            )


class GetCurrentUserCommand(BaseModel):
    """Access-токен для получения текущего пользователя."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    access_token: str


class GetCurrentUserResult(BaseModel):
    """Текущие ID, email и роль активного пользователя."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: UUID
    email: str
    role: Role
    first_name: str = ""
    last_name: str = ""
    middle_name: str = ""
    session_id: UUID | None = Field(default=None, exclude=True)


class GetCurrentUserHandler:
    """Проверяет access-токен и читает актуальные данные активного пользователя."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        token_service: TokenService,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            token_service: Сервис проверки и выпуска JWT.
        """
        self._uow_factory = uow_factory
        self._token_service = token_service

    async def handle(self, command: GetCurrentUserCommand) -> GetCurrentUserResult:
        """Проверяет токен и читает текущие данные пользователя из базы.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            ID, email и актуальная роль пользователя.

        Raises:
            AuthenticationError: Недействительный токен или недоступный пользователь.
        """
        decoded_access = self._token_service.decode_access(command.access_token)
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(decoded_access.user_id)

            if user is None or not user.is_active:
                raise AuthenticationError

            if (
                decoded_access.session_id is not None
                and not await uow.auth_sessions.is_active(
                    decoded_access.session_id, decoded_access.user_id
                )
            ):
                raise AuthenticationError

            return GetCurrentUserResult(
                id=user.id,
                email=user.email,
                role=user.role,
                first_name=user.first_name,
                last_name=user.last_name,
                middle_name=user.middle_name,
                session_id=decoded_access.session_id,
            )


class LogoutCommand(BaseModel):
    """Refresh-токен текущего браузера для отзыва при выходе."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    refresh_token: str


class LogoutHandler:
    """Отзывает refresh-токен и связанную серверную сессию."""

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], token_service: TokenService
    ) -> None:
        """Сохраняет зависимости сценария выхода.

        Args:
            uow_factory: Фабрика UoW для транзакции отзыва токена.
            token_service: Сервис проверки refresh JWT.
        """
        self._uow_factory = uow_factory
        self._token_service = token_service

    async def handle(self, command: LogoutCommand) -> None:
        """Проверяет refresh-токен и отзывает связанную сессию.

        Непригодный JWT завершает сценарий без обращения к БД. Отсутствующая
        или уже использованная запись не мешает повторному выходу. Ошибки
        обращения к БД передаются вызывающему коду. Сессия отзывается даже при
        повторном предъявлении старого токена после ротации. Cookie удаляет ручка.

        Args:
            command: Команда с refresh-токеном текущего браузера.
        """
        try:
            decoded_refresh = self._token_service.decode_refresh(command.refresh_token)
        except AuthenticationError:
            return

        async with self._uow_factory() as uow:
            await uow.users.consume_refresh_token(
                decoded_refresh.jti, decoded_refresh.user_id
            )
            if decoded_refresh.session_id is not None:
                await uow.auth_sessions.revoke(
                    decoded_refresh.session_id, decoded_refresh.user_id
                )
