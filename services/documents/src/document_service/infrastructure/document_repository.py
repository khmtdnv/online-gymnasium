from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from document_service.application.templates import (
    CreateTemplateCommand,
    TemplateConflictError,
)
from document_service.domain.certificate import CertificateData
from document_service.domain.document import DocumentJob, DocumentStatus
from document_service.infrastructure.models.document_event_outbox import (
    DocumentEventRow,
)
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

    def create_template_job(self, command: CreateTemplateCommand) -> DocumentJob:
        """Создаёт job+задачу один раз; повтор сравнивает тип и весь снимок полей.

        Args:
            command: Снимок документа и постоянный ключ его создателя.

        Returns:
            Новое либо уже созданное задание с теми же данными.

        Raises:
            TemplateConflictError: Ключ занят документом с другими данными.
        """
        payload = command.payload.model_dump(mode="json", exclude_none=True)
        try:
            with self._session.begin_nested():
                row = DocumentJobRow(
                    id=uuid4(),
                    creator_id=command.creator_id,
                    request_key=command.request_key,
                    document_type=command.document_type,
                    status="pending",
                    payload=payload,
                )
                self._session.add(row)
                self._session.flush()
                self._session.add(
                    DocumentTaskOutboxRow(
                        id=uuid4(),
                        document_job_id=row.id,
                        task_name="documents.generate_certificate",
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            if (
                getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                != "document_jobs_creator_request_unique"
            ):
                raise
            row = self._session.scalar(
                select(DocumentJobRow).where(
                    DocumentJobRow.creator_id == command.creator_id,
                    DocumentJobRow.request_key == command.request_key,
                )
            )
            if (
                row is None
                or row.document_type != command.document_type
                or row.payload != payload
            ):
                raise TemplateConflictError from exc
        return self._to_document_job(row)

    def list_jobs(self, creator_id: UUID, limit: int, offset: int) -> list[DocumentJob]:
        """Читает страницу только новых заданий указанного создателя."""
        rows = self._session.scalars(
            select(DocumentJobRow)
            .where(DocumentJobRow.creator_id == creator_id)
            .order_by(DocumentJobRow.created_at.desc(), DocumentJobRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_document_job(row) for row in rows]

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
            .where(DocumentJobRow.id == job_id, DocumentJobRow.status == "pending")
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
            .where(
                DocumentJobRow.id == job_id,
                DocumentJobRow.status.in_(("pending", "processing")),
            )
            .values(status=DocumentStatus.COMPLETED.value, object_key=object_key)
            .returning(DocumentJobRow)
        )
        row = self._session.execute(statement).scalar_one_or_none()
        self._add_event(row, "completed")

    def mark_failed(self, job_id: UUID, error_message: str) -> None:
        """Меняет статус задания на failed и сохраняет описание ошибки.

        Args:
            job_id: ID задания генерации документа.
            error_message: Описание ошибки без секретов и внутреннего traceback.
        """
        statement = (
            update(DocumentJobRow)
            .where(
                DocumentJobRow.id == job_id,
                DocumentJobRow.status.in_(("pending", "processing")),
            )
            .values(status=DocumentStatus.FAILED.value, error_message=error_message)
            .returning(DocumentJobRow)
        )
        row = self._session.execute(statement).scalar_one_or_none()
        self._add_event(row, "failed")

    def _add_event(self, row: DocumentJobRow | None, status: str) -> None:
        """Не отправляет ФИО и внутреннюю ошибку; исторические задания не уведомляют."""
        if row is None or row.creator_id is None:
            return
        event_id = uuid4()
        self._session.add(
            DocumentEventRow(
                event_id=event_id,
                envelope={
                    "event_id": str(event_id),
                    "event_source": "documents",
                    "event_type": f"documents.document.{status}",
                    "schema_version": 1,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "request_id": None,
                    "actor": {"source": "system", "id": "documents"},
                    "payload": {
                        "job_id": str(row.id),
                        "creator_id": str(row.creator_id),
                        "document_type": row.document_type,
                    },
                },
            )
        )

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
            creator_id=row.creator_id,
            request_key=row.request_key,
        )
