"""Потоковый адаптер MinIO; соединения не остаются занятыми после чтения."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import BinaryIO

from minio.error import InvalidResponseError, S3Error, ServerError
from urllib3 import PoolManager, Timeout
from urllib3.exceptions import HTTPError

from homework_service.config import HomeworkSettings
from minio import Minio


class MinioFileStorage:
    """Хранит байты в одном приватном bucket, не меняя SQL-метаданные."""

    def __init__(
        self, client: Minio, bucket: str, http_pool: PoolManager | None = None
    ) -> None:
        """Сохраняет уже настроенный SDK-клиент без сетевого запроса.

        Args:
            client: Клиент MinIO текущего процесса.
            bucket: Приватный bucket Homework.
            http_pool: Пул, созданный фабрикой процесса; иначе остаётся у владельца SDK.
        """
        self._client = client
        self._bucket = bucket
        self._http_pool = http_pool

    def close(self) -> None:
        """Освобождает только созданный для этого адаптера HTTP-пул."""
        if self._http_pool is not None:
            self._http_pool.clear()

    def list_objects(self, prefix: str) -> Iterator[tuple[str, datetime]]:
        """Читает объекты только своего префикса ленивыми страницами SDK.

        Args:
            prefix: Пространство homework/, не произвольный bucket.

        Yields:
            Ключ и aware-время MinIO; в памяти только текущая страница SDK.

        Raises:
            ValueError: Запрошено чужое пространство.
            OSError: Ошибка listing или некорректные метаданные объекта.
        """
        if prefix != "homework/":
            raise ValueError("Only the homework prefix can be listed")
        try:
            for item in self._client.list_objects(
                self._bucket, prefix=prefix, recursive=True
            ):
                if item.object_name is None or item.last_modified is None:
                    raise OSError("Storage returned invalid object metadata")
                yield item.object_name, item.last_modified
        except (S3Error, ServerError, InvalidResponseError, HTTPError, OSError) as exc:
            raise OSError("File storage unavailable") from exc

    def put(
        self, storage_key: str, stream: BinaryIO, size_bytes: int, content_type: str
    ) -> None:
        """Передаёт SDK поток и точный размер, не копируя весь файл в bytes.

        Args:
            storage_key: Отдельный серверный ключ попытки.
            stream: Проверенный seekable-поток, который закроет владелец.
            size_bytes: Реальный размер после проверки.
            content_type: Проверенный MIME.

        Raises:
            OSError: Сбой записи; результат сохранения может быть неизвестен.
        """
        try:
            stream.seek(0)
            self._client.put_object(
                bucket_name=self._bucket,
                object_name=storage_key,
                data=stream,
                length=size_bytes,
                content_type=content_type,
                num_parallel_uploads=1,
            )
        except (S3Error, ServerError, InvalidResponseError, HTTPError, OSError) as exc:
            raise OSError("File storage unavailable") from exc

    @contextmanager
    def open(self, storage_key: str) -> Iterator[BinaryIO]:
        """Отдаёт поток без загрузки всего объекта в память.

        Args:
            storage_key: Разрешённый серверный ключ вложения.

        Yields:
            Поток, который читается порциями до выхода из контекста.

        Raises:
            OSError: Сбой открытия или чтения объекта.
        """
        response = None
        try:
            response = self._client.get_object(self._bucket, storage_key)
            yield response
        except (S3Error, ServerError, InvalidResponseError, HTTPError, OSError) as exc:
            raise OSError("File storage unavailable") from exc
        finally:
            if response is not None:
                try:
                    response.close()
                finally:
                    response.release_conn()

    def delete(self, storage_key: str) -> None:
        """Удаляет только конкретный ключ, без очистки bucket или чужих префиксов.

        Args:
            storage_key: Ключ объекта, ненужность которого уже подтверждена БД.

        Raises:
            OSError: Сбой удаления.
        """
        try:
            self._client.remove_object(self._bucket, storage_key)
        except (S3Error, ServerError, InvalidResponseError, HTTPError, OSError) as exc:
            raise OSError("File storage unavailable") from exc


def create_file_storage(settings: HomeworkSettings) -> MinioFileStorage | None:
    """Собирает необязательное хранилище без пробного сетевого запроса.

    Args:
        settings: Endpoint, bucket и отдельные права приложения Homework.

    Returns:
        Хранилище либо None при неполной настройке; JSON-создание остаётся доступным.
    """
    if not all(
        (
            settings.minio_endpoint,
            settings.minio_bucket,
            settings.minio_access_key,
            settings.minio_secret_key and settings.minio_secret_key.get_secret_value(),
        )
    ):
        return None
    pool = PoolManager(
        maxsize=4,
        block=True,
        retries=False,
        timeout=Timeout(connect=5.0, read=120.0),
    )
    try:
        client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
            region="us-east-1",
            http_client=pool,
        )
    except BaseException:
        pool.clear()
        raise
    return MinioFileStorage(client, settings.minio_bucket, pool)
