"""Подключение только к собственной базе Homework."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    """Создаёт engine без немедленного подключения.

    Args:
        url: SQLAlchemy URL своей БД.

    Returns:
        Асинхронный engine.
    """
    return create_async_engine(url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику отдельных сессий.

    Args:
        engine: Engine собственной базы.

    Returns:
        Фабрика с сохранением загруженных полей после commit.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> None:
    """Проверяет доступность БД без записи данных.

    Args:
        engine: Проверяемый engine.

    Raises:
        SQLAlchemyError: Соединение или запрос не выполнены.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
