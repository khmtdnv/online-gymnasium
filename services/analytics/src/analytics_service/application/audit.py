"""Строгие события общего аудита и ограниченные запросы отчёта."""

import json
from datetime import UTC, date, timedelta
from typing import Literal, Self
from uuid import UUID, uuid5

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from analytics_service.application.snapshot import parse_lesson_snapshot


class StrictData(BaseModel):
    """Не допускает неизвестные поля, неявные типы и изменение после проверки."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Actor(StrictData):
    """Разделяет пространство UUID пользователей, staff-ID и системных событий."""

    source: Literal["gateway", "backoffice", "system", "service"]
    id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.source == "gateway":
            UUID(self.id)
        if self.source == "backoffice" and (
            not self.id.isascii()
            or not self.id.isdecimal()
            or not 0 < int(self.id) <= 9223372036854775807
        ):
            raise ValueError("Invalid staff identity")
        if self.source == "system" and self.id not in {
            "schedule",
            "billing",
            "documents",
        }:
            raise ValueError("Unknown system actor")
        if self.source == "service" and self.id != "backoffice":
            raise ValueError("Unknown calling service")
        return self


class ReviewPayload(StrictData):
    """Только ссылки, исторический класс и результат проверки."""

    answer_id: int = Field(ge=1, le=2147483647)
    homework_id: int = Field(ge=1, le=2147483647)
    student_id: UUID
    class_id: int = Field(ge=1, le=2147483647)
    subject_id: int = Field(ge=1, le=2147483647)
    teacher_id: UUID
    status: Literal["returned", "graded"]
    grade: int | None = Field(ge=2, le=5)

    @model_validator(mode="after")
    def validate_grade(self) -> Self:
        if (self.status == "graded") != (self.grade is not None):
            raise ValueError("Invalid review grade")
        return self


class PeriodReference(StrictData):
    period_id: int = Field(ge=1, le=2147483647)
    class_id: int = Field(ge=1, le=2147483647)


class StudentClassPayload(StrictData):
    """Старый контракт Journal остаётся совместимым с новым consumer."""

    operation: Literal["added", "transferred", "removed"]
    student_id: UUID
    previous: PeriodReference | None
    current: PeriodReference | None

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        expected = {
            "added": (False, True),
            "transferred": (True, True),
            "removed": (True, False),
        }
        if (self.previous is not None, self.current is not None) != expected[
            self.operation
        ]:
            raise ValueError("Invalid class transition")
        return self


class SchedulePayload(StrictData):
    """Снимок урока без выдуманного инициатора изменения."""

    lesson_id: int = Field(ge=1, le=2147483647)
    class_id: int = Field(ge=1, le=2147483647)
    teacher_id: UUID
    subject_id: int = Field(ge=1, le=2147483647)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: Literal["planned", "canceled"]
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("Invalid lesson interval")
        return self


class GatewayUserPayload(StrictData):
    """Факт о пользователе не содержит email, ФИО, пароль и токены."""

    user_id: UUID
    role: Literal["student", "teacher", "parent", "admin"]


class AdminActionPayload(StrictData):
    """Локальный результат команды; succeeded=False не выдаёт сбой за успех."""

    record_id: int = Field(ge=1, le=9223372036854775807)
    action: str = Field(min_length=1, max_length=64)
    succeeded: bool
    result_code: str = Field(max_length=64)
    target_ids: dict[str, str | int] = Field(max_length=8)

    @field_validator("target_ids")
    @classmethod
    def only_identifiers(cls, value):
        """Не позволяет случайному вложенному полю пронести credentials в UI."""
        allowed = {
            "user_id",
            "student_id",
            "parent_id",
            "teacher_id",
            "class_id",
            "period_id",
            "previous_period_id",
            "payment_id",
        }
        if not set(value) <= allowed:
            raise ValueError("Unknown target identifier")
        for item in value.values():
            if type(item) is int:
                if not 0 < item <= 9223372036854775807:
                    raise ValueError("Invalid numeric identifier")
            elif item.isascii() and item.isdecimal():
                if not 0 < int(item) <= 9223372036854775807:
                    raise ValueError("Invalid identifier")
            else:
                UUID(item)
        return value


class BillingPayload(StrictData):
    """Финансовый факт содержит ссылки/копейки, но не карточные реквизиты."""

    payment_id: int = Field(ge=1, le=2147483647)
    order_id: int = Field(ge=1, le=2147483647)
    student_id: UUID
    payer_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int = Field(ge=100, le=100000000)
    currency: Literal["RUB"]
    refund_actor_id: UUID | None = None

    @field_validator("study_month")
    @classmethod
    def first_day(cls, value: date) -> date:
        if value.day != 1 or not 2020 <= value.year <= 2100:
            raise ValueError("Invalid tuition month")
        return value


class DocumentPayload(StrictData):
    """Ссылка готовности без ФИО, текста документа и внутренней ошибки."""

    job_id: UUID
    creator_id: UUID
    document_type: Literal["certificate", "contract", "act", "receipt"]


class AuditEvent(StrictData):
    """Общий конверт с проверкой payload по объявленному источнику/типу."""

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
    schema_version: int = Field(ge=1, le=1)
    occurred_at: AwareDatetime
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    actor: Actor
    payload: dict

    @field_validator("occurred_at")
    @classmethod
    def supported_timestamp(cls, value):
        """Неподдерживаемое время уходит в DLQ, а не блокирует все новые события."""
        value = value.astimezone(UTC)
        if not 1900 <= value.year <= 2299:
            raise ValueError("Event timestamp exceeds ClickHouse range")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        contracts = {
            "documents.document.completed": ("documents", "system", DocumentPayload),
            "documents.document.failed": ("documents", "system", DocumentPayload),
            "billing.payment.succeeded": ("billing", "system", BillingPayload),
            "billing.payment.canceled": ("billing", "system", BillingPayload),
            "billing.payment.refunded": ("billing", "system", BillingPayload),
            "gateway.user.created": ("gateway", "service", GatewayUserPayload),
            "gateway.user.logged_in": ("gateway", "gateway", GatewayUserPayload),
            "backoffice.action.recorded": (
                "backoffice",
                "backoffice",
                AdminActionPayload,
            ),
            "homework.answer.reviewed": ("homework", "gateway", ReviewPayload),
            "journal.student_class.changed": (
                "journal",
                "backoffice",
                StudentClassPayload,
            ),
            "schedule.lesson.changed": ("schedule", "system", SchedulePayload),
        }
        contract = contracts.get(self.event_type)
        if contract is None or (self.event_source, self.actor.source) != contract[:2]:
            raise ValueError("Unknown event contract or source mismatch")
        if self.actor.source == "system" and self.actor.id != self.event_source:
            raise ValueError("System actor mismatch")
        payload = TypeAdapter(contract[2]).validate_json(json.dumps(self.payload))
        if (
            isinstance(payload, ReviewPayload)
            and str(payload.teacher_id) != self.actor.id
        ):
            raise ValueError("Review actor mismatch")
        if (
            isinstance(payload, GatewayUserPayload)
            and self.event_type == "gateway.user.logged_in"
            and str(payload.user_id) != self.actor.id
        ):
            raise ValueError("Login actor mismatch")
        return self


def parse_audit_event(raw: bytes) -> AuditEvent:
    """Разбирает ограниченный envelope; лишнее содержимое отправляется в DLQ.

    Args:
        raw: Исходные байты Kafka, не HTTP-запрос пользователя.

    Returns:
        Полностью проверенный конверт.

    Raises:
        ValueError: JSON, версия, поля или payload не соответствуют контракту.
    """
    if len(raw) > 262144:
        raise ValueError("Audit event exceeds size limit")
    return AuditEvent.model_validate_json(raw)


def parse_schedule_audit_event(raw: bytes) -> AuditEvent:
    """Адаптирует старый snapshot с числовым event_id к стабильному UUID аудита."""
    if len(raw) > 262144:
        raise ValueError("Schedule event exceeds size limit")
    snapshot = parse_lesson_snapshot(json.loads(raw))
    if snapshot is None:
        raise ValueError("Expected schedule snapshot")
    return AuditEvent(
        event_id=uuid5(
            UUID("87bc9da4-43a8-4f34-849f-c2b821f52025"),
            f"schedule:{snapshot.event_id}",
        ),
        event_source="schedule",
        event_type="schedule.lesson.changed",
        schema_version=1,
        occurred_at=snapshot.occurred_at.astimezone(UTC),
        actor=Actor(source="system", id="schedule"),
        payload=snapshot.model_dump(mode="json", exclude={"event_id", "occurred_at"}),
    )


class EventPeriod(BaseModel):
    """Ограниченный период событий по UTC-дням, обе даты включительно."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    date_from: date = Field(ge=date(1900, 1, 1), le=date(2299, 12, 30))
    date_to: date = Field(ge=date(1900, 1, 1), le=date(2299, 12, 30))

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        if (
            not timedelta(0) <= self.date_to - self.date_from < timedelta(days=366)
            or self.date_to == date.max
        ):
            raise ValueError("Expected period from1to366days")
        return self


class AuditQuery(EventPeriod):
    """Одна страница общего журнала с явными фильтрами."""

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


class ProgressQuery(EventPeriod):
    """Один исторический класс за период; отчёт не зависит от текущего состава."""

    class_id: int = Field(ge=1, le=2147483647)


class ProgressRow(StrictData):
    student_id: UUID
    subject_id: int
    graded_count: int
    average_grade: float
