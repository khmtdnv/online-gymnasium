from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from gateway_service.domain.user import Role, User


class DecodedRefresh(BaseModel):
    """ID пользователя и jti после проверки refresh-токена."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    user_id: UUID
    jti: UUID
    session_id: UUID | None = None


class DecodedAccess(BaseModel):
    """ID пользователя и роль из проверенного access-токена."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    user_id: UUID
    role: Role
    session_id: UUID | None = None


class IssuedRefresh(BaseModel):
    """Подписанный refresh-токен, его jti и срок действия."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    token: str
    jti: UUID
    expires_at: AwareDatetime


class TokenService(Protocol):
    """Контракт проверки и выпуска access- и refresh-токенов."""

    def decode_refresh(self, token: str) -> DecodedRefresh:
        """Проверяет подпись, срок действия и тип refresh-токена.

        Args:
            token: Строка JWT для проверки.

        Returns:
            ID пользователя и jti проверенного токена.

        Raises:
            AuthenticationError: Токен недействителен или его поля некорректны.
        """
        ...

    def decode_access(self, token: str) -> DecodedAccess:
        """Проверяет подпись, срок действия и тип access-токена.

        Args:
            token: Строка JWT для проверки.

        Returns:
            ID пользователя и роль из проверенного токена.

        Raises:
            AuthenticationError: Токен недействителен или его поля некорректны.
        """
        ...

    def issue_refresh(
        self, user: User, *, session_id: UUID | None = None
    ) -> IssuedRefresh:
        """Выпускает подписанный refresh-токен с новым jti.

        Не записывает токен в базу; сохранение выполняет вызывающий обработчик.

        Args:
            user: Пользователь с данными, нужными для операции.

        Returns:
            Токен, его jti и время окончания действия.
        """
        ...

    def issue_access(self, user: User, *, session_id: UUID | None = None) -> str:
        """Выпускает access-токен с ID пользователя и его ролью.

        Args:
            user: Пользователь с данными, нужными для операции.

        Returns:
            Подписанная строка JWT.
        """
        ...
