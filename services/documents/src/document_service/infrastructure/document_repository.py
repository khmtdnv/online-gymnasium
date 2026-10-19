from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from document_service.domain.certificate import CertificateData
from document_service.domain.document import DocumentJob, DocumentStatus
from document_service.infrastructure.models.document_job import DocumentJobRow
from document_service.infrastructure.models.document_task_outbox import (
    DocumentTaskOutboxRow,
)


class SqlAlchemyDocumentRepository:
    """Работает с заданиями документов в переданной сессии PostgreSQL."""

    def __init__(self, session: Session) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            session: Сессия текущей транзакции; commit остаётся за Unit of Work.
        """
        self._session = session

    def create_job_with_outbox(self, certificate: CertificateData) -> DocumentJob:
        """Записывает задание справки и намерение отправить задачу Celery.

        Обе записи используют одну сессию; commit выполняет Unit of Work.

        Args:
            certificate: Проверенные данные справки об обучении.

        Returns:
            Созданное задание со статусом pending.
        """
        job_id = uuid4()
        job_row = DocumentJobRow(
            id=job_id,
            document_type="certificate",
            status=DocumentStatus.PENDING.value,
            payload={
                "student_full_name": certificate.student_full_name,
                "class_name": certificate.class_name,
                "academic_year": certificate.academic_year,
            },
        )
        outbox_row = DocumentTaskOutboxRow(
            id=uuid4(),
            document_job_id=job_id,
            task_name="documents.generate_certificate",
        )
        self._session.add_all([job_row, outbox_row])
        self._session.flush()
        self._session.refresh(job_row)

        return self._to_document_job(job_row)

    def get_job(self, job_id: UUID) -> DocumentJob | None:
        """Ищет задание документа по ID.

        Args:
            job_id: ID задания генерации документа.

        Returns:
            Задание или None, если запись не найдена.
        """
        statement = select(DocumentJobRow).where(DocumentJobRow.id == job_id)
        row = self._session.scalar(statement)

        if row is None:
            return None

        return self._to_document_job(row)

    def mark_processing(self, job_id: UUID) -> None:
        """Меняет статус задания на processing в текущей транзакции.

        Args:
            job_id: ID задания генерации документа.
        """
        statement = (
            update(DocumentJobRow)
            .where(DocumentJobRow.id == job_id)
            .values(status=DocumentStatus.PROCESSING.value)
        )
        self._session.execute(statement)

    def mark_completed(self, job_id: UUID, object_key: str) -> None:
        """Меняет статус задания на completed и сохраняет ключ готового файла.

        Args:
            job_id: ID задания генерации документа.
            object_key: Ключ файла внутри бакета, например certificates/<job_id>.pdf.
        """
        statement = (
            update(DocumentJobRow)
            .where(DocumentJobRow.id == job_id)
            .values(status=DocumentStatus.COMPLETED.value, object_key=object_key)
        )
        self._session.execute(statement)

    def mark_failed(self, job_id: UUID, error_message: str) -> None:
        """Меняет статус задания на failed и сохраняет описание ошибки.

        Args:
            job_id: ID задания генерации документа.
            error_message: Описание ошибки без секретов и внутреннего traceback.
        """
        statement = (
            update(DocumentJobRow)
            .where(DocumentJobRow.id == job_id)
            .values(status=DocumentStatus.FAILED.value, error_message=error_message)
        )
        self._session.execute(statement)

    @staticmethod
    def _to_document_job(row: DocumentJobRow) -> DocumentJob:
        """Преобразует строку SQLAlchemy в состояние задания.

        Args:
            row: Строка задания, полученная через SQLAlchemy.

        Returns:
            Задание с типизированным DocumentStatus.
        """
        return DocumentJob(
            id=row.id,
            document_type=row.document_type,
            status=DocumentStatus(row.status),
            payload=row.payload,
            object_key=row.object_key,
            error_message=row.error_message,
            created_at=row.created_at,
        )
