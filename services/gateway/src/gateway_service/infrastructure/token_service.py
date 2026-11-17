from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt

from gateway_service.application.errors import AuthenticationError
from gateway_service.application.ports.token_service import (
    DecodedAccess,
    DecodedRefresh,
    IssuedRefresh,
)
from gateway_service.config import GatewaySettings
from gateway_service.domain.user import Role, User


class PyJwtTokenService:
    """Подписывает и проверяет JWT с заданным секретом и алгоритмом HS256."""

    def __init__(self, settings: GatewaySettings) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            settings: Настройки текущего сервиса.
        """
        self._settings = settings

    def decode_refresh(self, token: str) -> DecodedRefresh:
        """Проверяет подпись, срок действия и тип refresh-токена.

        Args:
            token: Строка JWT для проверки.

        Returns:
            ID пользователя и jti проверенного токена.

        Raises:
            AuthenticationError: Токен недействителен или его поля некорректны.
        """
        try:
            decoded_token = jwt.decode(
                jwt=token,
                key=self._settings.jwt_secret,
                algorithms=["HS256"],
                options={"require": ["sub", "jti", "exp", "type"]},
            )
            if decoded_token["type"] != "refresh":
                raise AuthenticationError

            return DecodedRefresh(
                user_id=UUID(decoded_token["sub"]),
                jti=UUID(decoded_token["jti"]),
                session_id=self._decode_session_id(decoded_token),
            )
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise AuthenticationError from exc

    def decode_access(self, token: str) -> DecodedAccess:
        """Проверяет подпись, срок действия и тип access-токена.

        Args:
            token: Строка JWT для проверки.

        Returns:
            ID пользователя и роль из проверенного токена.

        Raises:
            AuthenticationError: Токен недействителен или его поля некорректны.
        """
        try:
            decoded_token = jwt.decode(
                jwt=token,
                key=self._settings.jwt_secret,
                algorithms=["HS256"],
                options={"require": ["sub", "role", "exp", "type"]},
            )
            if decoded_token["type"] != "access":
                raise AuthenticationError

            return DecodedAccess(
                user_id=UUID(decoded_token["sub"]),
                role=Role(decoded_token["role"]),
                session_id=self._decode_session_id(decoded_token),
            )
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise AuthenticationError from exc

    @staticmethod
    def _decode_session_id(claims: dict) -> UUID | None:
        """Читает необязательный идентификатор сессии из проверенного JWT."""
        if "sid" not in claims:
            return None
        value = claims["sid"]
        if not isinstance(value, str):
            raise AuthenticationError
        return UUID(value)

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
        jti = uuid4()
        expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=self._settings.refresh_token_ttl_seconds
        )
        payload = {
            "sub": str(user.id),
            "jti": str(jti),
            "exp": expires_at,
            "type": "refresh",
        }
        if session_id is not None:
            payload["sid"] = str(session_id)
        token = jwt.encode(
            payload=payload, key=self._settings.jwt_secret, algorithm="HS256"
        )
        return IssuedRefresh(token=token, jti=jti, expires_at=expires_at)

    def issue_access(self, user: User, *, session_id: UUID | None = None) -> str:
        """Выпускает access-токен с ID пользователя и его ролью.

        Args:
            user: Пользователь с данными, нужными для операции.

        Returns:
            Подписанная строка JWT.
        """
        expires_at = datetime.now(tz=UTC) + timedelta(
            seconds=self._settings.access_token_ttl_seconds
        )
        payload = {
            "sub": str(user.id),
            "role": user.role.value,
            "exp": expires_at,
            "type": "access",
        }
        if session_id is not None:
            payload["sid"] = str(session_id)
        return jwt.encode(
            payload=payload,
            key=self._settings.jwt_secret,
            algorithm="HS256",
        )
