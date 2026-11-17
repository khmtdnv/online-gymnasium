"""Публичные DTO и минимальные проверяемые части внешнего API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenData(BaseModel):
    """Свои границы запрещают неизвестные поля и изменение данных."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentSnapshot(FrozenData):
    """Неизменные параметры повторного POST провайдеру, без сетевых credentials."""

    id: int = Field(strict=True, ge=1)
    order_id: int = Field(strict=True, ge=1)
    amount_kopecks: int = Field(strict=True, ge=100, le=100000000)
    provider_key: UUID
    provider_id: UUID | None = None


class RefundSnapshot(FrozenData):
    """Отдельная попытка полного возврата со своим постоянным ключом."""

    id: int = Field(strict=True, ge=1)
    provider_key: UUID
    provider_id: UUID | None = None
    payment: PaymentSnapshot


class PaymentState(PaymentSnapshot):
    """Сохранённая попытка для повторной сверки после разрыва связи."""

    created_at: datetime
    status: str


class RefundState(RefundSnapshot):
    """Время первой попытки не сдвигается при повторной отправке."""

    created_at: datetime
    status: str


class ProviderData(BaseModel):
    """Не сохраняет неизвестные внешние поля, например данные банковской карты."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class Money(ProviderData):
    """Десятичное строковое значение провайдера; float не участвует в расчётах."""

    value: str = Field(strict=True, pattern=r"^[0-9]{1,9}\.[0-9]{2}$")
    currency: Literal["RUB"]

    @property
    def kopecks(self) -> int:
        return int(Decimal(self.value) * 100)


class Recipient(ProviderData):
    """Магазин-получатель, подтверждённый ответом самого провайдера."""

    account_id: str = Field(strict=True)


class Confirmation(ProviderData):
    """Разрешён только redirect, не сбор карточных данных нашим приложением."""

    type: Literal["redirect"]
    confirmation_url: str = Field(strict=True, max_length=2048)


class ProviderPayment(ProviderData):
    """Необходимые факты, а не целый сырой объект с платёжными реквизитами."""

    id: UUID
    status: Literal["pending", "succeeded", "canceled"]
    paid: bool = Field(strict=True)
    test: bool = Field(strict=True)
    amount: Money
    recipient: Recipient
    metadata: dict[str, str]
    confirmation: Confirmation | None = None
    refundable: bool = Field(default=False, strict=True)
    refunded_amount: Money | None = None


class ProviderRefund(ProviderData):
    """Полный возврат с проверяемой ссылкой на известный тестовый платёж."""

    id: UUID
    status: Literal["pending", "succeeded", "canceled"]
    payment_id: UUID
    amount: Money


class ShopInfo(ProviderData):
    """Авторитетная проверка test-store до любого POST к ЮKassa."""

    account_id: str = Field(strict=True)
    test: bool = Field(strict=True)
    status: Literal["enabled", "disabled"]


class StartPayment(FrozenData):
    """Инициатор задан Gateway; сумма отсутствует в пользовательском вводе."""

    student_id: UUID
    payer_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    request_key: UUID

    @field_validator("study_month")
    @classmethod
    def first_day(cls, value: date) -> date:
        if value.day != 1 or not 2020 <= value.year <= 2100:
            raise ValueError("Expected first day of an education month")
        return value

    @model_validator(mode="after")
    def valid_quarter(self):
        if self.period_type == "quarter" and self.study_month.month not in {
            1,
            4,
            9,
            11,
        }:
            raise ValueError("Expected the first day of a study quarter")
        return self


class StartRefund(FrozenData):
    """Admin UUID задан Gateway, ключ повторяется при неизвестном результате."""

    actor_id: UUID
    request_key: UUID


PaymentStatus = Literal[
    "creating",
    "pending",
    "succeeded",
    "canceled",
    "unknown",
    "manual_review",
    "refunded",
]


class PaymentView(FrozenData):
    """Безопасный результат для портала: нет карты, секретов и сырого provider JSON."""

    id: int
    order_id: int
    student_id: UUID
    payer_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int
    currency: Literal["RUB"] = "RUB"
    status: PaymentStatus
    confirmation_url: str | None
    provider_id: UUID | None
    created_at: datetime
    refund_status: str | None = None


class OrderView(FrozenData):
    """Финансовый статус месяца никак не связан с активностью пользователя."""

    id: int
    student_id: UUID
    study_month: date
    period_type: Literal["month", "quarter"] = "month"
    amount_kopecks: int
    currency: Literal["RUB"] = "RUB"
    status: Literal["unpaid", "paid", "refunded"]
    payment: PaymentView | None
