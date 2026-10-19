from typing import Protocol

from pydantic import BaseModel, ConfigDict, InstanceOf

from schedule_service.domain.lesson import Lesson


class IdempotencyRecord(BaseModel):
    """Хеш прошлого запроса и связанный с ним урок, если он уже записан."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    request_hash: str
    lesson: InstanceOf[Lesson] | None


class IdempotencyRepository(Protocol):
    """Контракт резервирования и завершения повторного запроса."""

    async def claim(self, operation: str, key: str, request_hash: str) -> None:
        """Резервирует новый ключ в текущей транзакции.

        Args:
            operation: Название операции, в рамках которой уникален ключ запроса.
            key: Ключ повторного запроса, переданный клиентом.
            request_hash: Хеш данных запроса для проверки совпадения повторов.

        Raises:
            IdempotencyKeyAlreadyExists: Ключ операции уже занят.
        """
        ...

    async def get_by_key(self, operation: str, key: str) -> IdempotencyRecord | None:
        """Читает сохранённый результат после завершения конфликтной транзакции.

        Args:
            operation: Название операции, в рамках которой уникален ключ.
            key: Ключ повторяемой попытки.

        Returns:
            Хеш и связанный урок либо None, если ключ отсутствует.
        """
        ...

    async def complete(self, operation: str, key: str, lesson: Lesson) -> None:
        """Связывает зарезервированный ключ запроса с созданным уроком.

        Args:
            operation: Название операции, в рамках которой уникален ключ запроса.
            key: Ключ повторного запроса, переданный клиентом.
            lesson: Урок с данными для операции.
        """
        ...
