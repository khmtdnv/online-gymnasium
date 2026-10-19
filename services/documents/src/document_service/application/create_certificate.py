from pydantic import BaseModel, ConfigDict, field_validator

from document_service.application.ports.unit_of_work import DocumentUnitOfWorkFactory
from document_service.domain.certificate import CertificateData
from document_service.domain.document import DocumentJob


class CreateCertificateCommand(BaseModel):
    """Имя ученика, класс и учебный год для справки об обучении."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    student_full_name: str
    class_name: str
    academic_year: str

    @field_validator("student_full_name", "class_name", "academic_year")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        """Проверяет непустоту без изменения значения.

        Args:
            value: Поле справки.

        Returns:
            Исходное непустое значение.

        Raises:
            ValueError: Поле состоит только из пробелов.
        """
        if not value.strip():
            raise ValueError("Certificate data must not be blank")
        return value


class CreateCertificateHandler:
    """Проверяет данные справки и записывает задание вместе с outbox."""

    def __init__(self, uow_factory: DocumentUnitOfWorkFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    def handle(self, command: CreateCertificateCommand) -> DocumentJob:
        """Проверяет данные и создаёт задание справки с outbox.

        Args:
            command: Входные данные выполняемого сценария.

        Returns:
            Задание, принятое для дальнейшей генерации.

        Raises:
            InvalidCertificateData: Поля справки не заполнены.
        """
        certificate = CertificateData(
            student_full_name=command.student_full_name,
            class_name=command.class_name,
            academic_year=command.academic_year,
        )
        with self._uow_factory() as uow:
            return uow.documents.create_job_with_outbox(certificate)
