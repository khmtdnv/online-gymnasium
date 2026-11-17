"""Короткие локальные транзакции Billing, не удерживаемые во время HTTP ЮKassa."""

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from billing_service.contracts import (
    OrderView,
    PaymentState,
    PaymentView,
    ProviderPayment,
    ProviderRefund,
    RefundState,
    StartPayment,
    StartRefund,
)
from billing_service.models import (
    BillingEventRow,
    PaymentRow,
    RefundRow,
    TuitionOrderRow,
)

ACTIVE = ("creating", "pending", "unknown", "manual_review", "succeeded")


class BillingConflictError(Exception):
    """Ключ уже относится к другой операции либо заказ имеет активную попытку."""


class PaymentNotFoundError(Exception):
    """Платёж/возврат отсутствует; нельзя выдумывать его финансовый статус."""


def _constraint(error: IntegrityError):
    cause = getattr(error.orig, "driver_exception", None) or error.orig.__cause__
    return getattr(cause, "constraint_name", None)


def _state(payment: PaymentRow, order: TuitionOrderRow) -> PaymentState:
    return PaymentState(
        id=payment.id,
        order_id=order.id,
        amount_kopecks=order.amount_kopecks,
        provider_key=payment.provider_key,
        provider_id=payment.provider_id,
        status=payment.status,
        created_at=payment.created_at,
    )


def _view(
    payment: PaymentRow, order: TuitionOrderRow, refund_status=None
) -> PaymentView:
    return PaymentView(
        id=payment.id,
        order_id=order.id,
        student_id=order.student_id,
        payer_id=payment.payer_id,
        study_month=order.study_month,
        period_type=order.period_type,
        amount_kopecks=order.amount_kopecks,
        status=payment.status,
        confirmation_url=payment.confirmation_url,
        provider_id=payment.provider_id,
        created_at=payment.created_at,
        refund_status=refund_status,
    )


class BillingStore:
    """Заказ блокируется перед платёжной попыткой во всех изменяющих сценариях."""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def ensure_quarter_order(
        self, student_id: UUID, start: date, amount_kopecks: int
    ) -> None:
        """Создаёт счёт один раз, не меняя сумму существующего начисления."""
        if (
            start.day != 1
            or start.month not in {1, 4, 9, 11}
            or not 2020 <= start.year <= 2100
        ):
            raise ValueError("Expected start of study quarter")
        if not 100 <= amount_kopecks <= 100000000:
            raise ValueError("Invalid tuition amount")
        try:
            async with self._sessions() as session, session.begin():
                session.add(
                    TuitionOrderRow(
                        student_id=student_id,
                        study_month=start,
                        period_type="quarter",
                        amount_kopecks=amount_kopecks,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            if _constraint(exc) != "tuition_order_student_month":
                raise

    async def quarter_status(self, student_id, start):
        """Возвращает статус четвертного счёта, не смешивая его с месячным."""
        async with self._sessions() as session:
            return await session.scalar(
                select(TuitionOrderRow.status).where(
                    TuitionOrderRow.student_id == student_id,
                    TuitionOrderRow.study_month == start,
                    TuitionOrderRow.period_type == "quarter",
                )
            )

    async def reserve_payment(
        self, command: StartPayment, price_kopecks: int
    ) -> PaymentState:
        """Резервирует единственную активную попытку, до обращения к провайдеру."""
        try:
            async with self._sessions() as session, session.begin():
                if command.period_type == "month":
                    try:
                        async with session.begin_nested():
                            session.add(
                                TuitionOrderRow(
                                    student_id=command.student_id,
                                    study_month=command.study_month,
                                    period_type=command.period_type,
                                    amount_kopecks=price_kopecks,
                                )
                            )
                            await session.flush()
                    except IntegrityError as exc:
                        if _constraint(exc) != "tuition_order_student_month":
                            raise
                order = await session.scalar(
                    select(TuitionOrderRow)
                    .where(
                        TuitionOrderRow.student_id == command.student_id,
                        TuitionOrderRow.study_month == command.study_month,
                        TuitionOrderRow.period_type == command.period_type,
                    )
                    .with_for_update()
                )
                if order is None:
                    raise BillingConflictError
                existing = await session.scalar(
                    select(PaymentRow).where(
                        PaymentRow.payer_id == command.payer_id,
                        PaymentRow.request_key == command.request_key,
                    )
                )
                if existing:
                    if existing.order_id != order.id:
                        raise BillingConflictError
                    return _state(existing, order)
                active = await session.scalar(
                    select(PaymentRow.id).where(
                        PaymentRow.order_id == order.id, PaymentRow.status.in_(ACTIVE)
                    )
                )
                if active or order.status not in {"unpaid", "refunded"}:
                    raise BillingConflictError
                row = PaymentRow(
                    order_id=order.id,
                    payer_id=command.payer_id,
                    request_key=command.request_key,
                    provider_key=uuid4(),
                )
                session.add(row)
                await session.flush()
                state = _state(row, order)
            return state
        except IntegrityError as exc:
            if _constraint(exc) in {"payment_request_key", "payment_active_order"}:
                raise BillingConflictError from exc
            raise

    async def get_payment(self, payment_id: int) -> PaymentState:
        """Читает параметры неизменного provider-запроса для безопасной сверки."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(PaymentRow, TuitionOrderRow)
                    .join(TuitionOrderRow)
                    .where(PaymentRow.id == payment_id)
                )
            ).one_or_none()
            if row is None:
                raise PaymentNotFoundError
            return _state(*row)

    async def _locked_payment(self, session, payment_id):
        order_id = await session.scalar(
            select(PaymentRow.order_id).where(PaymentRow.id == payment_id)
        )
        if order_id is None:
            raise PaymentNotFoundError
        order = await session.scalar(
            select(TuitionOrderRow)
            .where(TuitionOrderRow.id == order_id)
            .with_for_update()
        )
        payment = await session.scalar(
            select(PaymentRow).where(PaymentRow.id == payment_id).with_for_update()
        )
        return payment, order

    async def _change_status(self, session, payment, order, new_status):
        """Вызывает outbox только при переходе; повтор не увеличивает аудит."""
        previous = payment.status
        payment.status = new_status
        payment.updated_at = datetime.now(UTC)
        if new_status == "succeeded":
            order.status = "paid"
        elif new_status == "refunded":
            order.status = "refunded"
        if previous != new_status and new_status in {
            "succeeded",
            "canceled",
            "refunded",
        }:
            event_id = uuid4()
            refund_actor = (
                await session.scalar(
                    select(RefundRow.actor_id).where(RefundRow.payment_id == payment.id)
                )
                if new_status == "refunded"
                else None
            )
            envelope = {
                "event_id": str(event_id),
                "event_source": "billing",
                "event_type": f"billing.payment.{new_status}",
                "schema_version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "request_id": None,
                "actor": {"source": "system", "id": "billing"},
                "payload": {
                    "payment_id": payment.id,
                    "order_id": order.id,
                    "student_id": str(order.student_id),
                    "payer_id": str(payment.payer_id),
                    "study_month": order.study_month.isoformat(),
                    "period_type": order.period_type,
                    "amount_kopecks": order.amount_kopecks,
                    "currency": "RUB",
                    "refund_actor_id": str(refund_actor) if refund_actor else None,
                },
            }
            session.add(BillingEventRow(event_id=event_id, envelope=envelope))

    async def apply_payment(
        self, payment_id: int, value: ProviderPayment
    ) -> PaymentView:
        """Старый pending/canceled не откатывает уже подтверждённую оплату/возврат."""
        async with self._sessions() as session, session.begin():
            payment, order = await self._locked_payment(session, payment_id)
            if payment.provider_id is not None and payment.provider_id != value.id:
                raise BillingConflictError
            payment.provider_id = value.id
            payment.updated_at = datetime.now(UTC)
            if payment.status not in {"refunded", "canceled"}:
                if (
                    value.refunded_amount
                    and value.refunded_amount.kopecks == order.amount_kopecks
                    and value.status == "succeeded"
                ):
                    await self._change_status(session, payment, order, "refunded")
                elif payment.status != "succeeded":
                    await self._change_status(session, payment, order, value.status)
            if value.status == "pending" and payment.status == "pending":
                payment.confirmation_url = value.confirmation.confirmation_url
            elif payment.status in {"succeeded", "canceled", "refunded"}:
                payment.confirmation_url = None
        return await self.view_payment(payment_id)

    async def mark_unknown(self, payment_id: int, *, manual=False):
        """Не выдаёт сетевую неопределённость за отмену или освобождение заказа."""
        async with self._sessions() as session, session.begin():
            payment, _ = await self._locked_payment(session, payment_id)
            if payment.status in {"creating", "unknown"}:
                payment.status = "manual_review" if manual else "unknown"
            payment.updated_at = datetime.now(UTC)

    async def reserve_refund(
        self, payment_id: int, command: StartRefund
    ) -> RefundState:
        """Связывает отдельный постоянный ключ с одной полной попыткой возврата."""
        try:
            async with self._sessions() as session, session.begin():
                payment, order = await self._locked_payment(session, payment_id)
                by_key = await session.scalar(
                    select(RefundRow).where(
                        RefundRow.actor_id == command.actor_id,
                        RefundRow.request_key == command.request_key,
                    )
                )
                existing = await session.scalar(
                    select(RefundRow).where(RefundRow.payment_id == payment_id)
                )
                if by_key:
                    if by_key.payment_id != payment_id:
                        raise BillingConflictError
                    existing = by_key
                elif existing or payment.status != "succeeded":
                    raise BillingConflictError
                if existing is None:
                    existing = RefundRow(
                        payment_id=payment_id,
                        actor_id=command.actor_id,
                        request_key=command.request_key,
                        provider_key=uuid4(),
                    )
                    session.add(existing)
                    await session.flush()
                result = RefundState(
                    id=existing.id,
                    provider_key=existing.provider_key,
                    provider_id=existing.provider_id,
                    status=existing.status,
                    created_at=existing.created_at,
                    payment=_state(payment, order),
                )
            return result
        except IntegrityError as exc:
            if _constraint(exc) in {"refund_request_key", "refund_payment_unique"}:
                raise BillingConflictError from exc
            raise

    async def get_refund(self, refund_id: int) -> RefundState:
        """Возвращает неизменные параметры полного возврата."""
        async with self._sessions() as session:
            refund = await session.get(RefundRow, refund_id)
            if refund is None:
                raise PaymentNotFoundError
            payment = await session.get(PaymentRow, refund.payment_id)
            order = await session.get(TuitionOrderRow, payment.order_id)
            return RefundState(
                id=refund.id,
                provider_key=refund.provider_key,
                provider_id=refund.provider_id,
                status=refund.status,
                created_at=refund.created_at,
                payment=_state(payment, order),
            )

    async def apply_refund(self, refund_id: int, value: ProviderRefund):
        """Сохраняет refund/status, payment/order и событие в одной транзакции."""
        state = await self.get_refund(refund_id)
        async with self._sessions() as session, session.begin():
            payment, order = await self._locked_payment(session, state.payment.id)
            refund = await session.scalar(
                select(RefundRow).where(RefundRow.id == refund_id).with_for_update()
            )
            if refund.provider_id is not None and refund.provider_id != value.id:
                raise BillingConflictError
            refund.provider_id = value.id
            refund.updated_at = datetime.now(UTC)
            if refund.status not in {"succeeded", "canceled"}:
                refund.status = value.status
            if refund.status == "succeeded":
                await self._change_status(session, payment, order, "refunded")
                payment.confirmation_url = None
        return await self.view_payment(state.payment.id)

    async def mark_refund_unknown(self, refund_id: int, *, manual=False):
        async with self._sessions() as session, session.begin():
            refund = await session.scalar(
                select(RefundRow).where(RefundRow.id == refund_id).with_for_update()
            )
            if refund is None:
                raise PaymentNotFoundError
            if refund.status in {"creating", "unknown"}:
                refund.status = "manual_review" if manual else "unknown"
            refund.updated_at = datetime.now(UTC)

    async def view_payment(self, payment_id: int) -> PaymentView:
        """Возвращает минимальный пользовательский DTO, без provider credentials."""
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(PaymentRow, TuitionOrderRow, RefundRow.status)
                    .join(TuitionOrderRow)
                    .outerjoin(RefundRow, RefundRow.payment_id == PaymentRow.id)
                    .where(PaymentRow.id == payment_id)
                )
            ).one_or_none()
            if result is None:
                raise PaymentNotFoundError
            return _view(*result)

    async def list_orders(
        self, student_id: UUID, limit: int, offset: int
    ) -> list[OrderView]:
        """Читает страницу месяцев и последнюю попытку каждого, не имитирует оплату."""
        async with self._sessions() as session:
            latest = (
                select(PaymentRow.id)
                .where(PaymentRow.order_id == TuitionOrderRow.id)
                .order_by(PaymentRow.id.desc())
                .limit(1)
                .correlate(TuitionOrderRow)
                .scalar_subquery()
            )
            rows = await session.execute(
                select(TuitionOrderRow, PaymentRow, RefundRow.status)
                .select_from(TuitionOrderRow)
                .outerjoin(PaymentRow, PaymentRow.id == latest)
                .outerjoin(RefundRow, RefundRow.payment_id == PaymentRow.id)
                .where(TuitionOrderRow.student_id == student_id)
                .order_by(TuitionOrderRow.study_month.desc(), TuitionOrderRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [
                OrderView(
                    id=order.id,
                    student_id=order.student_id,
                    study_month=order.study_month,
                    period_type=order.period_type,
                    amount_kopecks=order.amount_kopecks,
                    status=order.status,
                    payment=_view(payment, order, refund_status) if payment else None,
                )
                for order, payment, refund_status in rows
            ]

    async def list_payments(self, limit: int, offset: int) -> list[PaymentView]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(PaymentRow, TuitionOrderRow, RefundRow.status)
                .join(TuitionOrderRow)
                .outerjoin(RefundRow, RefundRow.payment_id == PaymentRow.id)
                .order_by(PaymentRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [_view(*row) for row in rows]

    async def refund_by_request(
        self, actor_id: UUID, request_key: UUID
    ) -> RefundState | None:
        """Ищет именно прежнюю команду, в том числе после потери успешногоACK."""
        async with self._sessions() as session:
            refund_id = await session.scalar(
                select(RefundRow.id).where(
                    RefundRow.actor_id == actor_id, RefundRow.request_key == request_key
                )
            )
        return await self.get_refund(refund_id) if refund_id is not None else None

    async def find_provider(self, provider_id: UUID, *, refund=False) -> int | None:
        model = RefundRow if refund else PaymentRow
        async with self._sessions() as session:
            return await session.scalar(
                select(model.id).where(model.provider_id == provider_id)
            )

    async def pending_ids(self, *, refund=False) -> list[int]:
        model = RefundRow if refund else PaymentRow
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(model.id)
                    .where(model.status.in_(("creating", "unknown", "pending")))
                    .order_by(model.updated_at, model.id)
                    .limit(20)
                )
            )

    async def pending_events(self) -> list[dict]:
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(BillingEventRow.envelope)
                    .where(BillingEventRow.published_at.is_(None))
                    .order_by(BillingEventRow.created_at, BillingEventRow.event_id)
                    .limit(100)
                )
            )

    async def mark_published(self, event_id: UUID):
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(BillingEventRow)
                .where(
                    BillingEventRow.event_id == event_id,
                    BillingEventRow.published_at.is_(None),
                )
                .values(published_at=datetime.now(UTC))
            )
