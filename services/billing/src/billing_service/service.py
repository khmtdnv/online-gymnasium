"""Сеть выполняется между локальными транзакциями, не внутри row-lock."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from billing_service.contracts import PaymentView, StartPayment, StartRefund
from billing_service.provider import (
    ProviderUnavailableError,
    RefundNotAllowedError,
    YooKassaClient,
)
from billing_service.storage import BillingConflictError, BillingStore
from billing_service.study_quarters import study_quarter_for_date


class BillingService:
    """Резервирует, сверяет и возвращает честный результат финансовой попытки."""

    def __init__(
        self,
        store: BillingStore,
        provider: YooKassaClient | None,
        price_kopecks: int,
        quarter_price_kopecks: int = 900000,
    ) -> None:
        self.store, self.provider, self.price_kopecks = store, provider, price_kopecks
        self.quarter_price_kopecks = quarter_price_kopecks

    def require_provider(self) -> YooKassaClient:
        if self.provider is None:
            raise ProviderUnavailableError
        return self.provider

    async def quarter_access(self, student_id, today) -> bool:
        """За учебную четверть требуется подтверждённый платёж; летом долга нет."""
        quarter = study_quarter_for_date(today)
        if quarter is None:
            return True
        return await self.store.quarter_status(student_id, quarter.start) == "paid"

    async def start_payment(self, command: StartPayment) -> PaymentView:
        """Сначала исключает реальный магазин, затем резервирует попытку вPG."""
        await self.require_provider().check_test_shop()
        price = (
            self.quarter_price_kopecks
            if command.period_type == "quarter"
            else self.price_kopecks
        )
        state = await self.store.reserve_payment(command, price)
        return await self.refresh_payment(state.id)

    async def refresh_payment(
        self, payment_id: int, *, provider_id: UUID | None = None
    ) -> PaymentView:
        """Просроченный неизвестныйPOST не повторяется с новым или прежнимkey."""
        state = await self.store.get_payment(payment_id)
        if provider_id is not None:
            if state.provider_id is not None and state.provider_id != provider_id:
                raise BillingConflictError
            state = state.model_copy(update={"provider_id": provider_id})
        if state.status in {"refunded", "canceled"}:
            return await self.store.view_payment(state.id)
        if state.provider_id is None and datetime.now(
            UTC
        ) - state.created_at >= timedelta(hours=23):
            await self.store.mark_unknown(state.id, manual=True)
            return await self.store.view_payment(state.id)
        try:
            provider = self.require_provider()
            value = (
                await provider.get_payment(state)
                if state.provider_id
                else await provider.create_payment(state)
            )
            return await self.store.apply_payment(state.id, value)
        except ProviderUnavailableError:
            await self.store.mark_unknown(state.id)
            raise

    async def request_refund(
        self, payment_id: int, command: StartRefund
    ) -> PaymentView:
        """Идемпотентный повтор существующей попытки не зависит от refundableпослеACK."""
        provider = self.require_provider()
        await provider.check_test_shop()
        existing = await self.store.refund_by_request(
            command.actor_id, command.request_key
        )
        if existing:
            if existing.payment.id != payment_id:
                raise BillingConflictError
            return await self.refresh_refund(existing.id)
        payment = await self.store.get_payment(payment_id)
        checked = await provider.get_payment(payment)
        if (
            checked.status != "succeeded"
            or not checked.refundable
            or (checked.refunded_amount and checked.refunded_amount.kopecks)
        ):
            # Параллельный такой же запрос мог уже успеть выполнить возврат.
            existing = await self.store.refund_by_request(
                command.actor_id, command.request_key
            )
            if existing and existing.payment.id == payment_id:
                return await self.refresh_refund(existing.id)
            await self.store.apply_payment(payment_id, checked)
            raise RefundNotAllowedError
        state = await self.store.reserve_refund(payment_id, command)
        return await self.refresh_refund(state.id)

    async def refresh_refund(self, refund_id: int) -> PaymentView:
        """Сверяет прежнюю попытку возврата, не создавая новую при потере ответа."""
        state = await self.store.get_refund(refund_id)
        if state.status in {"succeeded", "canceled", "manual_review"}:
            return await self.store.view_payment(state.payment.id)
        if state.provider_id is None and datetime.now(
            UTC
        ) - state.created_at >= timedelta(hours=23):
            await self.store.mark_refund_unknown(state.id, manual=True)
            return await self.store.view_payment(state.payment.id)
        try:
            provider = self.require_provider()
            value = (
                await provider.get_refund(state)
                if state.provider_id
                else await provider.create_refund(state)
            )
            return await self.store.apply_refund(state.id, value)
        except ProviderUnavailableError, RefundNotAllowedError:
            await self.store.mark_refund_unknown(state.id)
            raise

    async def webhook(self, event: str, provider_id: UUID) -> None:
        """Тело webhook — только сигнал сделать собственный GET, не факт оплаты."""
        refund = event == "refund.succeeded"
        local_id = await self.store.find_provider(provider_id, refund=refund)
        if local_id is None:
            return
        if refund:
            await self.refresh_refund(local_id)
        else:
            await self.refresh_payment(local_id)
