from datetime import datetime
from typing import Protocol
from uuid import UUID

from gateway_service.domain.user import Role, User


class UserRepository(Protocol):
    """Контракт хранения пользователей, связей и одноразовых refresh-токенов."""

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Ищет пользователя по ID.

        Args:
            user_id: ID пользователя Gateway.

        Returns:
            Пользователь или None, если запись не найдена.
        """
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Ищет пользователя по email.

        Args:
            email: Email пользователя.

        Returns:
            Пользователь или None, если запись не найдена.
        """
        ...

    async def create_user(self, user: User) -> None:
        """Записывает нового пользователя в текущей транзакции.

        Args:
            user: Пользователь с данными, нужными для операции.

        Raises:
            EmailAlreadyExistsError: Email уже занят другим пользователем.
        """
        ...

    async def list_users(self) -> list[User]:
        """Читает пользователей в порядке email.

        Returns:
            Список пользователей; при отсутствии записей пустой список.
        """
        ...

    async def search_users(
        self, query: str, role: Role | None, active_only: bool, limit: int
    ) -> list[User]:
        """Ищет слова в ФИО и email с фильтрами и ограничением результата."""
        ...

    async def update_user_names(
        self, user_id: UUID, first_name: str, last_name: str, middle_name: str
    ) -> User | None:
        """Меняет ФИО; возвращает пользователя либо None, если ID не найден."""
        ...

    async def create_parent_student_link(
        self, parent_id: UUID, student_id: UUID
    ) -> bool:
        """Добавляет связь родителя и ученика, если её ещё нет.

        Args:
            parent_id: ID пользователя с ролью родителя.
            student_id: ID пользователя с ролью ученика.

        Returns:
            True для новой связи; False для уже существующей пары.
        """
        ...

    async def create_refresh_token(
        self, token_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        """Записывает новый refresh-токен с его jti и сроком действия.

        Args:
            token_id: jti refresh-токена; совпадает с ID его записи в базе.
            user_id: ID пользователя Gateway.
            expires_at: Дата и время окончания действия токена.
        """
        ...

    async def consume_refresh_token(self, token_id: UUID, user_id: UUID) -> bool:
        """Помечает действующий неиспользованный refresh-токен использованным.

        Проверка условий и изменение выполняются одним UPDATE внутри транзакции.

        Args:
            token_id: jti refresh-токена; совпадает с ID его записи в базе.
            user_id: ID пользователя Gateway.

        Returns:
            True при успешной отметке; False, если токен нельзя использовать.
        """
        ...
