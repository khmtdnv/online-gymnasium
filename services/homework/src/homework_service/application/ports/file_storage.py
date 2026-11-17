"""Потоковый доступ к приватным объектам без зависимости приложения от MinIO."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from typing import BinaryIO, Protocol


class FileStorage(Protocol):
    """Синхронные операции выполняются вызывающим кодом в ограниченном threadpool."""

    def list_objects(self, prefix: str) -> Iterator[tuple[str, datetime]]:
        """Перечисляет собственные объекты постранично, без накопления всего bucket.

        Args:
            prefix: Только пространство приложения homework/.

        Returns:
            Ленивый iterator ключа и времени последнего изменения.

        Raises:
            OSError: Хранилище не позволило прочитать страницу.
        """
        ...

    def put(
        self, storage_key: str, stream: BinaryIO, size_bytes: int, content_type: str
    ) -> None:
        """Сохраняет проверенный поток по приватному серверному ключу.

        Args:
            storage_key: Отдельный ключ текущей попытки, не имя пользователя.
            stream: Seekable-поток; остаётся собственностью вызывающего кода.
            size_bytes: Проверенный размер содержимого.
            content_type: MIME, установленный после проверки байтов.

        Raises:
            OSError: Объект не сохранён либо результат сетевой операции неизвестен.
        """
        ...

    def open(self, storage_key: str) -> AbstractContextManager[BinaryIO]:
        """Открывает чтение с обязательным освобождением соединения при выходе.

        Args:
            storage_key: Приватный ключ разрешённого вложения.

        Returns:
            Контекстный менеджер читаемого потока.

        Raises:
            OSError: Объект отсутствует или хранилище недоступно.
        """
        ...

    def delete(self, storage_key: str) -> None:
        """Удаляет только указанный объект после проверки его ненужности в БД.

        Args:
            storage_key: Приватный ключ ненужной попытки.

        Raises:
            OSError: Хранилище не подтвердило удаление.
        """
        ...
