"""Контракты оплаты Gateway, независимые от внутренних моделей Billing."""

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BillingData(BaseModel):
    """Неизменяемые данные с запретом неизвестных полей."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CheckoutBody(BillingData):
    """Сумму и инициатора определяет сервер, не браузер."""

    student_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    request_key: UUID

    @field_validator("study_month")
    @classmethod
    def check_month(cls, value: date) -> date:
        if value.day != 1 or not 2020 <= value.year <= 2100:
            raise ValueError("Expected first day of study month")
        return value

    @model_validator(mode="after")
    def check_quarter(self):
        if self.period_type == "quarter" and self.study_month.month not in {
            1,
            4,
            9,
            11,
        }:
            raise ValueError("Expected start of study quarter")
        return self


class RefundBody(BillingData):
    """Повторный возврат использует тот же ключ, а UUID admin берётся из JWT."""

    request_key: UUID


class ReconcileBody(BillingData):
    """ID из кабинета провайдера не считается подтверждением оплаты."""

    provider_id: UUID | None = None


class BillingConfig(BillingData):
    """Публичная цена и готовность настройки, без секретов магазина."""

    configured: bool = Field(strict=True)
    test_only: Literal[True]
    price_kopecks: int = Field(strict=True, ge=100, le=100000000)
    quarter_price_kopecks: int = Field(
        default=900000, strict=True, ge=100, le=100000000
    )
    currency: Literal["RUB"]


class Payment(BillingData):
    """Проверенный платёж без карточных данных и служебных ключей."""

    id: int = Field(strict=True, ge=1, le=2147483647)
    order_id: int = Field(strict=True, ge=1, le=2147483647)
    student_id: UUID
    payer_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int = Field(strict=True, ge=100, le=100000000)
    currency: Literal["RUB"]
    status: Literal[
        "creating",
        "pending",
        "succeeded",
        "canceled",
        "unknown",
        "manual_review",
        "refunded",
    ]
    confirmation_url: str | None
    provider_id: UUID | None
    created_at: datetime
    refund_status: (
        Literal[
            "creating", "pending", "succeeded", "canceled", "unknown", "manual_review"
        ]
        | None
    ) = None

    @field_validator("confirmation_url")
    @classmethod
    def check_redirect(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = urlsplit(value)
        host = url.hostname or ""
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.port not in (None, 443)
            or not any(
                host == allowed or host.endswith("." + allowed)
                for allowed in ("yoomoney.ru", "yookassa.ru")
            )
        ):
            raise ValueError("Untrusted provider redirect")
        return value


class NamedPayment(Payment):
    """Административная история с актуальным ФИО ученика из Gateway."""

    student_name: str


class TuitionOrder(BillingData):
    """Последняя попытка оплаты конкретного месяца ученика."""

    id: int = Field(strict=True, ge=1, le=2147483647)
    student_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int = Field(strict=True, ge=100, le=100000000)
    currency: Literal["RUB"]
    status: Literal["unpaid", "paid", "refunded"]
    payment: Payment | None

    @model_validator(mode="after")
    def same_order(self):
        if self.payment and (
            self.payment.order_id != self.id
            or self.payment.student_id != self.student_id
            or self.payment.study_month != self.study_month
            or self.payment.period_type != self.period_type
            or self.payment.amount_kopecks != self.amount_kopecks
        ):
            raise ValueError("Payment belongs to another order")
        return self


class BillingStudent(BillingData):
    """ФИО ученика из Gateway, не копия профиля в финансовой БД."""

    id: UUID
    name: str
