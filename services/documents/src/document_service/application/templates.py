"""Проверенные снимки данных учебных документов; не юридические документы."""

from datetime import date
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
Name = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300),
]


class TemplateConflictError(Exception):
    """Тот же ключ создания уже использован для другого документа или данных."""


class TemplateData(BaseModel):
    """Неизменяемые поля без произвольных URL, HTML-шаблонов и неизвестных ключей."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SchoolDocumentData(TemplateData):
    """Общие данные справки/договора и необязательный период акта."""

    student_full_name: Name
    class_name: Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=64
        ),
    ]
    academic_year: str = Field(pattern=r"^[0-9]{4}/[0-9]{4}$", strict=True)
    period_from: date | None = None
    period_to: date | None = None

    @field_validator("academic_year")
    @classmethod
    def consecutive_years(cls, value: str) -> str:
        """Разрешает только два последовательных календарных года."""
        first, second = map(int, value.split("/"))
        if not 1900 <= first <= 9998 or second != first + 1:
            raise ValueError("Expected consecutive study years")
        return value


class ReceiptData(TemplateData):
    """Снимок подтверждённого тестового платежа, собранный Gateway."""

    payment_id: int = Field(strict=True, ge=1, le=2147483647)
    student_full_name: Name
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int = Field(strict=True, ge=100, le=100000000)
    currency: Literal["RUB"] = "RUB"

    @field_validator("study_month")
    @classmethod
    def first_day(cls, value: date) -> date:
        """Месяц оплаты хранится как его первое число."""
        if value.day != 1 or not 2020 <= value.year <= 2100:
            raise ValueError("Expected first day of study month")
        return value


class TemplateRequest(TemplateData):
    """Ключ повтора, тип и снимок полей нового задания."""

    request_key: UUID
    document_type: DocumentType
    payload: SchoolDocumentData | ReceiptData

    @model_validator(mode="after")
    def compatible_payload(self):
        """Не смешивает квитанцию с полями справки и требует период для акта."""
        if self.document_type == "receipt":
            if not isinstance(self.payload, ReceiptData):
                raise ValueError("Receipt requires verified payment data")
        elif not isinstance(self.payload, SchoolDocumentData):
            raise ValueError("Expected school document data")
        elif self.document_type == "act":
            start, end = self.payload.period_from, self.payload.period_to
            if start is None or end is None or not 0 <= (end - start).days <= 366:
                raise ValueError("Expected act period of at most 366 days")
        elif self.payload.period_from is not None or self.payload.period_to is not None:
            raise ValueError("Period is only allowed for act")
        return self


class CreateTemplateCommand(TemplateRequest):
    """Создатель задан доверенной границей Gateway, не полем формы."""

    creator_id: UUID
