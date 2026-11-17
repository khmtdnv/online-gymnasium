from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Общая база SQLAlchemy-моделей и их метаданных внутри сервиса."""
