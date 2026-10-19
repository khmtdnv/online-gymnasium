from sqlalchemy import Engine
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.orm import Session, sessionmaker


def create_engine(url: str) -> Engine:
    """Создаёт объект подключения SQLAlchemy к базе данных.

    Args:
        url: URL подключения к базе с выбранным драйвером.

    Returns:
        Engine для открытия соединений и управления их пулом.
    """
    return create_sync_engine(url)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Создаёт фабрику новых сессий SQLAlchemy.

    Args:
        engine: Объект SQLAlchemy для соединений с базой.

    Returns:
        Фабрика, выдающая отдельную сессию для каждой транзакции.
    """
    return sessionmaker(engine)
