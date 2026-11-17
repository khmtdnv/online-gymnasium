"""Независимые публичные DTO аналитики, без импорта кода владельца данных."""

from datetime import date, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventPeriod(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        """Ограничивает стоимость чтения и исключает переполнение правой границы."""
        if (
            not timedelta(0) <= self.date_to - self.date_from < timedelta(days=366)
            or self.date_to == date.max
        ):
            raise ValueError("Invalid report period")
        return self


class ProgressQuery(EventPeriod):
    class_id: int = Field(ge=1, le=2147483647)


class AuditQuery(EventPeriod):
    event_source: (
        Literal[
            "homework",
            "journal",
            "schedule",
            "gateway",
            "backoffice",
            "billing",
            "documents",
        ]
        | None
    ) = None
    event_type: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


class ProgressRow(BaseModel):
    """Оценки, а не финансовые суммы; среднее может быть дробным."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    student_id: UUID
    subject_id: int = Field(strict=True, ge=1, le=2147483647)
    graded_count: int = Field(strict=True, ge=1)
    average_grade: float = Field(ge=2, le=5, allow_inf_nan=False)


class NamedProgressRow(ProgressRow):
    student_name: str
    subject_name: str


class AuditActor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: Literal["gateway", "backoffice", "system", "service"]
    id: str = Field(min_length=1, max_length=128)


class AuditEvent(BaseModel):
    """Проверенный конверт служебного Analytics API, только для администратора."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: UUID
    event_source: Literal[
        "homework",
        "journal",
        "schedule",
        "gateway",
        "backoffice",
        "billing",
        "documents",
    ]
    event_type: str = Field(min_length=1, max_length=100)
    schema_version: int = Field(strict=True, ge=1, le=1)
    occurred_at: AwareDatetime
    request_id: str | None
    actor: AuditActor
    payload: dict
