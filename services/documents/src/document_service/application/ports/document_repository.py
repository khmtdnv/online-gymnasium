from typing import Protocol
from uuid import UUID

from document_service.domain.certificate import CertificateData
from document_service.domain.document import DocumentJob


class DocumentRepository(Protocol):
    """Контракт хранения заданий генерации и изменения их статусов."""

    def create_job_with_outbox(self, certificate: CertificateData) -> DocumentJob:
        """Записывает задание справки и намерение отправить задачу Celery.

        Обе записи используют одну сессию; commit выполняет Unit of Work.

        Args:
            certificate: Проверенные данные справки об обучении.

        Returns:
            Созданное задание со статусом pending.
        """
        ...

    def get_job(self, job_id: UUID) -> DocumentJob | None:
        """Ищет задание документа по ID.

        Args:
            job_id: ID задания генерации документа.

        Returns:
            Задание или None, если запись не найдена.
        """
        ...

    def mark_processing(self, job_id: UUID) -> None:
        """Меняет статус задания на processing в текущей транзакции.

        Args:
            job_id: ID задания генерации документа.
        """
        ...

    def mark_completed(self, job_id: UUID, object_key: str) -> None:
        """Меняет статус задания на completed и сохраняет ключ готового файла.

        Args:
            job_id: ID задания генерации документа.
            object_key: Ключ файла внутри бакета, например certificates/<job_id>.pdf.
        """
        ...

    def mark_failed(self, job_id: UUID, error_message: str) -> None:
        """Меняет статус задания на failed и сохраняет описание ошибки.

        Args:
            job_id: ID задания генерации документа.
            error_message: Описание ошибки без секретов и внутреннего traceback.
        """
        ...
