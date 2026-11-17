"""Уведомления используют только нужные проверенные контракты общих событий."""

import json
from datetime import UTC, date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class EventConflictError(Exception):
    """Один event_id повторился с другим содержимым; прежнее уведомление неизменно."""


class FrozenData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Actor(FrozenData):
    source: Literal["gateway", "system"]
    id: str


class Review(FrozenData):
    answer_id: int = Field(ge=1, le=2147483647)
    homework_id: int = Field(ge=1, le=2147483647)
    student_id: UUID
    class_id: int = Field(ge=1, le=2147483647)
    subject_id: int = Field(ge=1, le=2147483647)
    teacher_id: UUID
    status: Literal["returned", "graded"]
    grade: int | None = Field(ge=2, le=5)

    @model_validator(mode="after")
    def valid_grade(self):
        if (self.status == "graded") != (self.grade is not None):
            raise ValueError("Invalid review grade")
        return self


class Billing(FrozenData):
    payment_id: int = Field(ge=1, le=2147483647)
    order_id: int = Field(ge=1, le=2147483647)
    student_id: UUID
    payer_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int = Field(ge=100, le=100000000)
    currency: Literal["RUB"]
    refund_actor_id: UUID | None = None

    @model_validator(mode="after")
    def valid_month(self):
        if self.study_month.day != 1 or not 2020 <= self.study_month.year <= 2100:
            raise ValueError("Invalid tuition month")
        return self


class Document(FrozenData):
    job_id: UUID
    creator_id: UUID
    document_type: Literal["certificate", "contract", "act", "receipt"]


CONTRACTS = {
    "homework.answer.reviewed": ("homework", Review),
    "billing.payment.succeeded": ("billing", Billing),
    "billing.payment.canceled": ("billing", Billing),
    "billing.payment.refunded": ("billing", Billing),
    "documents.document.completed": ("documents", Document),
    "documents.document.failed": ("documents", Document),
}


class TargetEvent(FrozenData):
    """Строго проверенное событие перед записью в локальную inbox-транзакцию."""

    event_id: UUID
    event_source: Literal["homework", "billing", "documents"]
    event_type: str
    schema_version: int = Field(ge=1, le=1)
    occurred_at: AwareDatetime
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    actor: Actor
    payload: dict

    @model_validator(mode="after")
    def check_source_and_payload(self):
        expected = CONTRACTS.get(self.event_type)
        if expected is None or self.event_source != expected[0]:
            raise ValueError("Unknown notification event contract")
        if not 1900 <= self.occurred_at.astimezone(UTC).year <= 2299:
            raise ValueError("Unsupported event date")
        if self.event_source == "homework":
            if self.actor.source != "gateway":
                raise ValueError("Expected teacher actor")
            UUID(self.actor.id)
        elif self.actor.source != "system" or self.actor.id != self.event_source:
            raise ValueError("Unexpected system actor")
        expected[1].model_validate_json(json.dumps(self.payload))
        return self


def parse_event(raw: bytes) -> TargetEvent | None:
    """Разбирает нужный тип, остальные сообщения общего топика оставляет владельцам.

    Args:
        raw: Kafka JSON, не пользовательский HTTP-запрос.

    Returns:
        Проверенное событие либо None для ненужного этому каналу типа.

    Raises:
        ValueError: Размер, JSON, источник или целевой payload нарушает контракт.
    """
    if len(raw) > 262144:
        raise ValueError("Event exceeds limit")
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("event_type"), str):
        raise ValueError("Expected event object")  # noqa: TRY004 - ошибка контракта JSON
    if value["event_type"] not in CONTRACTS:
        return None
    return TargetEvent.model_validate_json(raw)


class Notification(FrozenData):
    """Безопасная запись для личного списка, без исходного события и его digest."""

    id: int = Field(ge=1, le=2147483647)
    event_id: UUID
    recipient_id: UUID
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=500)
    link: str = Field(min_length=1, max_length=200)
    created_at: AwareDatetime
    read_at: AwareDatetime | None


def describe_event(event: TargetEvent):
    """Получателей и относительный путь выводит из ссылок, а не произвольного URL."""
    data = event.payload
    if event.event_source == "documents":
        completed = event.event_type.endswith(".completed")
        return (
            {UUID(data["creator_id"])},
            "Документ готов" if completed else "Не удалось подготовить документ",
            "PDF можно открыть и скачать в списке ваших документов."
            if completed
            else "Откройте задание для проверки состояния.",
            f"/documents/{UUID(data['job_id'])}",
        )
    if event.event_source == "billing":
        titles = {
            "succeeded": "Тестовая оплата подтверждена",
            "canceled": "Тестовый платёж отменён",
            "refunded": "Тестовый возврат подтверждён",
        }
        return (
            {UUID(data["student_id"]), UUID(data["payer_id"])},
            titles[event.event_type.rsplit(".", 1)[1]],
            "Сведения доступны в разделе оплаты обучения.",
            "/billing",
        )
    graded = data["status"] == "graded"
    return (
        {UUID(data["student_id"])},
        "Домашнее задание проверено" if graded else "Работу нужно доработать",
        f"Оценка: {data['grade']}."
        if graded
        else "Преподаватель вернул работу на доработку.",
        f"/homework/{data['homework_id']}",
    )
