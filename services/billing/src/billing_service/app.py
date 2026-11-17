"""Закрытые маршруты Billing; пользовательскую связь с учеником проверяет Gateway."""

import secrets
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from billing_service.contracts import (
    FrozenData,
    OrderView,
    PaymentView,
    StartPayment,
    StartRefund,
)
from billing_service.provider import ProviderUnavailableError, RefundNotAllowedError
from billing_service.service import BillingService
from billing_service.storage import BillingConflictError, PaymentNotFoundError


class PageQuery(BaseModel):
    """Ограниченная страница, без возможности добавлять произвольные фильтры."""

    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


class OrderQuery(PageQuery):
    """Ученик задан проверенным Gateway, не данными роли из браузера."""

    student_id: UUID


class ReconcileBody(FrozenData):
    """Позволяет admin сверить найденный в кабинете provider_id, но не подменить сумму."""

    provider_id: UUID | None = None


class WebhookNotice(FrozenData):
    """Минимальный сигнал, без доверия к статусу из входящего webhook."""

    event: Literal["payment.succeeded", "payment.canceled", "refund.succeeded"]
    object_id: UUID


def create_app(
    service: BillingService, service_token: str, *, lifespan=None
) -> FastAPI:
    """Собирает приватный API и безопасные ответы ошибок без сырого provider JSON."""
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    bearer = HTTPBearer(auto_error=False)

    def require_gateway(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if (
            not service_token
            or credentials is None
            or not secrets.compare_digest(
                credentials.credentials.encode(), service_token.encode()
            )
        ):
            raise HTTPException(
                401,
                "Invalid service credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def conflict(request, exc):
        return JSONResponse(
            status_code=409,
            content={"code": "billing_conflict"},
            headers={"Cache-Control": "private, no-store"},
        )

    async def missing(request, exc):
        return JSONResponse(
            status_code=404,
            content={"code": "payment_not_found"},
            headers={"Cache-Control": "private, no-store"},
        )

    async def unavailable(request, exc):
        return JSONResponse(
            status_code=503,
            content={"code": "billing_unavailable"},
            headers={"Cache-Control": "private, no-store"},
        )

    app.add_exception_handler(BillingConflictError, conflict)
    app.add_exception_handler(RefundNotAllowedError, conflict)
    app.add_exception_handler(PaymentNotFoundError, missing)
    app.add_exception_handler(ProviderUnavailableError, unavailable)
    app.add_exception_handler(SQLAlchemyError, unavailable)
    router = APIRouter(prefix="/internal", dependencies=[Depends(require_gateway)])
    Id = Annotated[int, Path(ge=1, le=2147483647)]

    @router.get("/students/{student_id}/quarter-access")
    async def quarter_access(student_id: UUID, response: Response):
        """Отвечает по текущей дате демо-школы, а не дате из запроса."""
        response.headers["Cache-Control"] = "private, no-store"
        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        return {"allowed": await service.quarter_access(student_id, today)}

    @router.get("/config")
    async def config(response: Response):
        """Наличие ключей не выдаётся за подтверждение конкретного платежа."""
        response.headers["Cache-Control"] = "private, no-store"
        return {
            "configured": service.provider is not None,
            "test_only": True,
            "price_kopecks": service.price_kopecks,
            "quarter_price_kopecks": service.quarter_price_kopecks,
            "currency": "RUB",
        }

    @router.get("/orders", response_model=list[OrderView])
    async def orders(response: Response, query: Annotated[OrderQuery, Query()]):
        """Читает страницу только указанного доверенным Gateway ученика."""
        response.headers["Cache-Control"] = "private, no-store"
        return await service.store.list_orders(
            query.student_id, query.limit, query.offset
        )

    @router.get("/payments", response_model=list[PaymentView])
    async def payments(response: Response, query: Annotated[PageQuery, Query()]):
        """Полный административный список, недоступный публично напрямую."""
        response.headers["Cache-Control"] = "private, no-store"
        return await service.store.list_payments(query.limit, query.offset)

    @router.get("/payments/{payment_id}", response_model=PaymentView)
    async def payment(response: Response, payment_id: Id):
        response.headers["Cache-Control"] = "private, no-store"
        return await service.store.view_payment(payment_id)

    @router.post("/payments", response_model=PaymentView, status_code=202)
    async def start(body: StartPayment, response: Response):
        """202 не означает оплату: реальный статус находится в DTO."""
        response.headers["Cache-Control"] = "private, no-store"
        return await service.start_payment(body)

    @router.post("/payments/{payment_id}/refresh", response_model=PaymentView)
    async def refresh(payment_id: Id, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        return await service.refresh_payment(payment_id)

    @router.post("/payments/{payment_id}/reconcile", response_model=PaymentView)
    async def reconcile(payment_id: Id, body: ReconcileBody, response: Response):
        """Привязка требует совпадения metadata/магазина/суммы через GET, не на слово."""
        response.headers["Cache-Control"] = "private, no-store"
        return await service.refresh_payment(payment_id, provider_id=body.provider_id)

    @router.post(
        "/payments/{payment_id}/refund", response_model=PaymentView, status_code=202
    )
    async def refund(payment_id: Id, body: StartRefund, response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        return await service.request_refund(payment_id, body)

    @router.post("/webhook")
    async def webhook(body: WebhookNotice):
        """200 после проверки/записи либо для неизвестного локальной системе ID."""
        await service.webhook(body.event, body.object_id)
        return {"accepted": True}

    app.include_router(router)

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    return app
