from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class DocumentStatus(Enum):
    """Состояния задания: ожидает, выполняется, завершено или завершилось ошибкой."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DocumentJob:
    """Состояние задания генерации и ключ готового файла в хранилище."""

    id: UUID
    document_type: str
    status: DocumentStatus
    payload: dict[str, object]
    object_key: str | None
    error_message: str | None
    created_at: datetime
    creator_id: UUID | None = None
    request_key: UUID | None = None
