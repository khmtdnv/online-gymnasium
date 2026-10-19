from uuid import UUID

from pydantic import BaseModel, ConfigDict

from document_service.application.ports.unit_of_work import DocumentUnitOfWorkFactory


class MarkJobFailedCommand(BaseModel):
    """ID задания и безопасное описание причины неудачи."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    job_id: UUID
    error_message: str


class MarkJobFailedHandler:
    """Записывает окончательную ошибку задания в отдельной транзакции."""

    def __init__(self, uow_factory: DocumentUnitOfWorkFactory) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
        """
        self._uow_factory = uow_factory

    def handle(self, command: MarkJobFailedCommand) -> None:
        """Записывает окончательный статус failed и описание ошибки задания.

        Args:
            command: Входные данные выполняемого сценария.
        """
        with self._uow_factory() as uow:
            uow.documents.mark_failed(command.job_id, command.error_message)
