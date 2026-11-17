"""Общая metadata моделей собственной БД."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс ORM-моделей Homework."""
