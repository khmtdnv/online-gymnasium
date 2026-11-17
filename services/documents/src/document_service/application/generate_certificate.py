from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from document_service.application.errors import (
    PermanentDocumentError,
)
from document_service.application.ports.certificate_renderer import CertificateRenderer
from document_service.application.ports.document_storage import DocumentStorage
from document_service.application.ports.unit_of_work import DocumentUnitOfWorkFactory
from document_service.application.templates import TemplateRequest
from document_service.domain.certificate import CertificateData, InvalidCertificateData
from document_service.domain.document import DocumentStatus


class GenerateCertificateCommand(BaseModel):
    """ID задания, по которому нужно построить и сохранить справку."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    job_id: UUID


class GenerateCertificateHandler:
    """Строит PDF и сохраняет файл до отметки успешного завершения задания."""

    def __init__(
        self,
        uow_factory: DocumentUnitOfWorkFactory,
        renderer: CertificateRenderer,
        storage: DocumentStorage,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            renderer: Генератор PDF по данным справки.
            storage: Хранилище файлов PDF.
        """
        self._uow_factory = uow_factory
        self._renderer = renderer
        self._storage = storage

    def handle(self, command: GenerateCertificateCommand) -> None:
        """Строит PDF, загружает его и отмечает задание завершённым.

        Генерация и загрузка идут вне транзакции. Нет задания или оно уже
        завершено/failed: ничего не делает. Повторная загрузка использует тот же ключ
        файла.

        Args:
            command: Входные данные выполняемого сценария.

        Raises:
            PermanentDocumentError: В данных справки отсутствуют или не заполнены поля.
            TemporaryStorageError: Хранилище не приняло PDF.
        """
        with self._uow_factory() as uow:
            job = uow.documents.get_job(command.job_id)

            if (
                job is None
                or job.status is DocumentStatus.COMPLETED
                or job.status is DocumentStatus.FAILED
            ):
                return

            uow.documents.mark_processing(command.job_id)

        try:
            if not isinstance(job.payload, dict):
                raise InvalidCertificateData("Certificate payload must be an object")
            if job.creator_id is not None:
                verified = TemplateRequest(
                    request_key=job.request_key,
                    document_type=job.document_type,
                    payload=job.payload,
                )
                pdf_bytes = self._renderer.render_document(
                    job.document_type,
                    verified.payload.model_dump(mode="json", exclude_none=True),
                )
            else:
                certificate = CertificateData(
                    student_full_name=job.payload["student_full_name"],
                    class_name=job.payload["class_name"],
                    academic_year=job.payload["academic_year"],
                )
                pdf_bytes = self._renderer.render(certificate)
        except (InvalidCertificateData, KeyError, ValidationError, ValueError) as exc:
            with self._uow_factory() as uow:
                uow.documents.mark_failed(command.job_id, "Document generation failed")

            raise PermanentDocumentError from exc

        directory = "documents" if job.creator_id is not None else "certificates"
        object_key = f"{directory}/{command.job_id}.pdf"
        self._storage.put_pdf(object_key, pdf_bytes)

        with self._uow_factory() as uow:
            uow.documents.mark_completed(command.job_id, object_key)
