from io import BytesIO

from minio import Minio
from minio.error import ServerError
from urllib3.exceptions import HTTPError

from document_service.application.errors import TemporaryStorageError


class MinioDocumentStorage:
    """Читает и сохраняет PDF в настроенном бакете MinIO."""

    def __init__(self, client: Minio, bucket: str) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            client: Настроенный клиент внешнего хранилища.
            bucket: Название существующего бакета MinIO.
        """
        self._client = client
        self._bucket = bucket

    def read(self, object_key: str) -> bytes:
        """Читает весь документ из хранилища по ключу.

        Args:
            object_key: Ключ файла внутри бакета, например certificates/<job_id>.pdf.

        Returns:
            Байты содержимого PDF.
        """
        minio_response = self._client.get_object(self._bucket, object_key)

        try:
            return minio_response.read()
        finally:
            minio_response.close()
            minio_response.release_conn()

    def put_pdf(self, object_key: str, pdf_bytes: bytes) -> None:
        """Сохраняет PDF по заданному ключу с типом application/pdf.

        Args:
            object_key: Ключ файла внутри бакета, например certificates/<job_id>.pdf.
            pdf_bytes: Содержимое PDF в байтах.

        Raises:
            TemporaryStorageError: Не удалась загрузка из-за сетевой ошибки или ошибки
                сервера.
        """
        try:
            self._client.put_object(
                bucket_name=self._bucket,
                object_name=object_key,
                data=BytesIO(pdf_bytes),
                length=len(pdf_bytes),
                content_type="application/pdf",
            )
        except (HTTPError, ServerError) as exc:
            raise TemporaryStorageError from exc
