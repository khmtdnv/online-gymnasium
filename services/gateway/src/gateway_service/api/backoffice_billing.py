"""Закрытое чтение финансовой истории для Backoffice."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from gateway_service.api.billing import named_payment_history
from gateway_service.api.dependencies import require_backoffice_service_token
from gateway_service.application.billing import NamedPayment

router = APIRouter(
    prefix="/internal/backoffice/billing",
    dependencies=[Depends(require_backoffice_service_token)],
    include_in_schema=False,
)


@router.get("/payments", response_model=list[NamedPayment])
async def get_payments(
    request: Request,
    response: Response,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
) -> list[NamedPayment]:
    """Возвращает страницу платежей доверенному Backoffice."""
    return await named_payment_history(request, response, offset)
