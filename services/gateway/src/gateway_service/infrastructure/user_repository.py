from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gateway_service.application.errors import EmailAlreadyExistsError
from gateway_service.domain.user import Role, User
from gateway_service.infrastructure.models.parent_student_link import (
    ParentStudentLinkRow,
)
from gateway_service.infrastructure.models.refresh_token import RefreshTokenRow
from gateway_service.infrastructure.models.user import UserRow


class SqlAlchemyUserRepository:
    """Работает с пользователями и токенами в переданной сессии PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            session: Сессия текущей транзакции; commit остаётся за Unit of Work.
        """
        self._session = session

    @staticmethod
    def _to_domain_model(db_model: UserRow) -> User:
        """Преобразует строку SQLAlchemy в пользователя приложения.

        Args:
            db_model: Строка пользователя, полученная через SQLAlchemy.

        Returns:
            Пользователь с ролью Role вместо строки базы.
        """
        return User(
            id=db_model.id,
            email=db_model.email,
            role=Role(db_model.role),
            password_hash=db_model.password_hash,
            is_active=db_model.is_active,
            first_name=db_model.first_name,
            last_name=db_model.last_name,
            middle_name=db_model.middle_name or "",
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Ищет пользователя по ID.

        Args:
            user_id: ID пользователя Gateway.

        Returns:
            Пользователь или None, если запись не найдена.
        """
        statement = select(UserRow).where(UserRow.id == user_id)
        row = await self._session.execute(statement)
        result = row.scalar_one_or_none()

        if result is None:
            return

        return self._to_domain_model(result)

    async def get_by_email(self, email: str) -> User | None:
        """Ищет пользователя по email.

        Args:
            email: Email пользователя.

        Returns:
            Пользователь или None, если запись не найдена.
        """
        statement = select(UserRow).where(UserRow.email == email)
        row = await self._session.execute(statement)
        result = row.scalar_one_or_none()

        if result is None:
            return

        return self._to_domain_model(result)

    async def create_user(self, user: User) -> None:
        """Записывает нового пользователя в текущей транзакции.

        Args:
            user: Пользователь с данными, нужными для операции.

        Raises:
            EmailAlreadyExistsError: Email уже занят другим пользователем.
        """
        statement = (
            insert(UserRow)
            .values(
                id=user.id,
                email=user.email,
                role=user.role.value,
                password_hash=user.password_hash,
                is_active=user.is_active,
                first_name=user.first_name,
                last_name=user.last_name,
                middle_name=user.middle_name,
            )
            .on_conflict_do_nothing(constraint="users_email_unique")
            .returning(UserRow.id)
        )
        result = await self._session.scalar(statement)
        if result is None:
            raise EmailAlreadyExistsError

    async def list_users(self) -> list[User]:
        """Читает пользователей в порядке email.

        Returns:
            Список пользователей; при отсутствии записей пустой список.
        """
        statement = select(UserRow).order_by(UserRow.email)
        rows = await self._session.execute(statement)
        results_list = rows.scalars().all()

        users_list = []
        for result in results_list:
            users_list.append(self._to_domain_model(result))

        return users_list

    async def search_users(
        self, query: str, role: Role | None, active_only: bool, limit: int
    ) -> list[User]:
        """Ищет каждое слово в любом поле ФИО или email без учёта регистра.

        Args:
            query: Проверенная непустая строка поиска.
            role: Ограничение роли либо None для всех ролей.
            active_only: Исключать ли неактивные учётные записи.
            limit: Проверенное максимальное число результатов.

        Returns:
            Пользователи в стабильном порядке; символы % и _ ищутся буквально.
        """
        statement = select(UserRow)
        for word in query.split():
            statement = statement.where(
                or_(
                    UserRow.last_name.icontains(word, autoescape=True),
                    UserRow.first_name.icontains(word, autoescape=True),
                    UserRow.middle_name.icontains(word, autoescape=True),
                    UserRow.email.icontains(word, autoescape=True),
                )
            )
        if role is not None:
            statement = statement.where(UserRow.role == role.value)
        if active_only:
            statement = statement.where(UserRow.is_active.is_(True))
        statement = statement.order_by(
            UserRow.last_name, UserRow.first_name, UserRow.email, UserRow.id
        ).limit(limit)
        rows = await self._session.scalars(statement)
        return [self._to_domain_model(row) for row in rows]

    async def update_user_names(
        self, user_id: UUID, first_name: str, last_name: str, middle_name: str
    ) -> User | None:
        """Обновляет только ФИО одним UPDATE; commit остаётся у Unit of Work."""
        statement = (
            update(UserRow)
            .where(UserRow.id == user_id)
            .values(first_name=first_name, last_name=last_name, middle_name=middle_name)
            .returning(UserRow)
        )
        row = await self._session.scalar(statement)
        return None if row is None else self._to_domain_model(row)

    async def create_parent_student_link(
        self,
        parent_id: UUID,
        student_id: UUID,
    ) -> bool:
        """Добавляет связь родителя и ученика, если её ещё нет.

        Args:
            parent_id: ID пользователя с ролью родителя.
            student_id: ID пользователя с ролью ученика.

        Returns:
            True для новой связи; False для уже существующей пары.
        """
        statement = (
            insert(ParentStudentLinkRow)
            .values(id=uuid4(), parent_id=parent_id, student_id=student_id)
            .on_conflict_do_nothing(
                constraint="parent_student_links_parent_student_unique"
            )
            .returning(ParentStudentLinkRow.id)
        )
        inserted_id = await self._session.scalar(statement)
        return inserted_id is not None

    async def create_refresh_token(
        self, token_id: UUID, user_id: UUID, expires_at: datetime
    ) -> None:
        """Записывает новый refresh-токен с его jti и сроком действия.

        Args:
            token_id: jti refresh-токена; совпадает с ID его записи в базе.
            user_id: ID пользователя Gateway.
            expires_at: Дата и время окончания действия токена.
        """
        statement = insert(RefreshTokenRow).values(
            id=token_id, user_id=user_id, expires_at=expires_at
        )
        await self._session.execute(statement)

    async def consume_refresh_token(self, token_id: UUID, user_id: UUID) -> bool:
        """Помечает действующий неиспользованный refresh-токен использованным.

        Проверка условий и изменение выполняются одним UPDATE внутри транзакции.

        Args:
            token_id: jti refresh-токена; совпадает с ID его записи в базе.
            user_id: ID пользователя Gateway.

        Returns:
            True при успешной отметке; False, если токен нельзя использовать.
        """
        statement = (
            update(RefreshTokenRow)
            .values(consumed_at=func.now())
            .where(
                RefreshTokenRow.id == token_id,
                RefreshTokenRow.user_id == user_id,
                RefreshTokenRow.expires_at > func.now(),
                RefreshTokenRow.consumed_at.is_(None),
            )
            .returning(RefreshTokenRow.id)
        )
        updated_id = await self._session.scalar(statement)
        return updated_id is not None
