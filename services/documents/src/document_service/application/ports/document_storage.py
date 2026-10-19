from typing import Protocol


class DocumentStorage(Protocol):
    """Контракт чтения PDF и сохранения файла по заданному ключу."""

    def read(self, object_key: str) -> bytes:
        """Читает весь документ из хранилища по ключу.

        Args:
            object_key: Ключ файла внутри бакета, например certificates/<job_id>.pdf.

        Returns:
            Байты содержимого PDF.
        """
        ...

    def put_pdf(self, object_key: str, pdf_bytes: bytes) -> None:
        """Сохраняет PDF по заданному ключу с типом application/pdf.

        Args:
            object_key: Ключ файла внутри бакета, например certificates/<job_id>.pdf.
            pdf_bytes: Содержимое PDF в байтах.

        Raises:
            TemporaryStorageError: Не удалась загрузка из-за сетевой ошибки или ошибки
                сервера.
        """
        ...
