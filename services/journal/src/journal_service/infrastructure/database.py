from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    """Создаёт объект подключения SQLAlchemy к базе данных.

    Args:
        url: URL подключения к базе с выбранным драйвером.

    Returns:
        Engine для открытия соединений и управления их пулом.
    """
    return create_async_engine(url=url)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику новых сессий SQLAlchemy.

    Args:
        engine: Объект SQLAlchemy для соединений с базой.

    Returns:
        Фабрика, выдающая отдельную сессию для каждой транзакции.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> None:
    """Проверяет подключение к БД запросом SELECT 1, не изменяя данные.

    Args:
        engine: Engine с настройками проверяемой базы.

    Raises:
        SQLAlchemyError: Не удалось подключиться или выполнить запрос.
    """
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
