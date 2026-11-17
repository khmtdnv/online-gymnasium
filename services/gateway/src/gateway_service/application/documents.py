"""Контракты учебных PDF на публичной границе портала."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

DocumentType = Literal["certificate", "contract", "act", "receipt"]


class DocumentData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SchoolDocumentFields(DocumentData):
    """Поля трёх учебных образцов, которые сотрудник заполняет вручную."""

    student_full_name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=300
        ),
    ]
    class_name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=64
        ),
    ]
    academic_year: str = Field(strict=True, pattern=r"^[0-9]{4}/[0-9]{4}$")
    period_from: date | None = None
    period_to: date | None = None

    @field_validator("academic_year")
    @classmethod
    def consecutive_years(cls, value: str) -> str:
        first, second = map(int, value.split("/"))
        if not 1900 <= first <= 9998 or second != first + 1:
            raise ValueError("Expected consecutive study years")
        return value


class ReceiptReference(DocumentData):
    """Квитанция принимает только ID платежа, без суммы и утверждения paid."""

    payment_id: int = Field(strict=True, ge=1, le=2147483647)


class CreateDocumentBody(DocumentData):
    """Тип, ключ повтора и разрешённые поля выбранного учебного шаблона."""

    document_type: DocumentType
    request_key: UUID
    payload: SchoolDocumentFields | ReceiptReference

    @model_validator(mode="after")
    def compatible_fields(self):
        if self.document_type == "receipt":
            if not isinstance(self.payload, ReceiptReference):
                raise ValueError("Receipt only accepts payment reference")
        elif not isinstance(self.payload, SchoolDocumentFields):
            raise ValueError("Expected school document fields")
        elif self.document_type == "act":
            start, end = self.payload.period_from, self.payload.period_to
            if start is None or end is None or not 0 <= (end - start).days <= 366:
                raise ValueError("Expected act period of at most 366 days")
        elif self.payload.period_from is not None or self.payload.period_to is not None:
            raise ValueError("Period only applies to act")
        return self


class CreatedDocument(DocumentData):
    """Задание может уже завершиться, если это повтор прежнего ключа."""

    id: UUID
    document_type: DocumentType
    status: Literal["pending", "processing", "completed", "failed"]


class DocumentJob(CreatedDocument):
    """Статус без ФИО, служебного object_key и внутренней ошибки."""

    created_at: datetime
    download_url: str | None = None
