"""Оплата учеником/родителем и административный возврат через закрытый Billing."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.billing import (
    BillingConfig,
    BillingStudent,
    CheckoutBody,
    NamedPayment,
    Payment,
    ReconcileBody,
    RefundBody,
    TuitionOrder,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.billing_client import BillingRequestError
from gateway_service.infrastructure.journal_client import JournalUnavailableError

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])
Viewer = Annotated[
    GetCurrentUserResult, Depends(RequireRoles((Role.STUDENT, Role.PARENT, Role.ADMIN)))
]
Admin = Annotated[GetCurrentUserResult, Depends(RequireRoles((Role.ADMIN,)))]
Id = Annotated[int, Path(ge=1, le=2147483647)]


async def call(request, method, *args):
    """Показывает известный отказ, но не раскрывает внутренний HTTP-ответ."""
    client = request.app.state.billing_client
    if client is None:
        raise HTTPException(503, "Billing unavailable")
    try:
        return await getattr(client, method)(*args)
    except BillingRequestError as exc:
        raise HTTPException(exc.status, "Billing request failed") from exc


async def check_student(request, viewer, student_id):
    """Повторно читает текущую связь родителя; совпадения payer_id недостаточно."""
    try:
        async with request.app.state.uow_factory() as uow:
            student = await uow.users.get_by_id(student_id)
            allowed = viewer.role == Role.ADMIN or (
                viewer.role == Role.STUDENT and viewer.id == student_id
            )
            if viewer.role == Role.PARENT:
                allowed = await uow.users.has_parent_student_link(viewer.id, student_id)
            if not allowed or student is None or student.role != Role.STUDENT:
                raise HTTPException(403, "Access denied")
            return student
    except SQLAlchemyError as exc:
        raise HTTPException(503, "User data unavailable") from exc


@router.get("/config", response_model=BillingConfig)
async def config(request: Request, response: Response, viewer: Viewer):
    """Цена приходит с сервера, наличие настроек не равно успешной оплате."""
    response.headers["Cache-Control"] = "private, no-store"
    return await call(request, "config")


@router.get("/students", response_model=list[BillingStudent])
async def students(request: Request, response: Response, viewer: Viewer):
    """Не загружает всех учеников школы: родителю выдаёт только связанных детей."""
    response.headers["Cache-Control"] = "private, no-store"
    try:
        async with request.app.state.uow_factory() as uow:
            if viewer.role == Role.PARENT:
                rows = await uow.users.list_children(viewer.id, limit=101)
                if len(rows) > 100:
                    raise HTTPException(503, "Too many linked students")
            elif viewer.role == Role.STUDENT:
                row = await uow.users.get_by_id(viewer.id)
                rows = [row] if row else []
            else:
                rows = []
        return [
            BillingStudent(
                id=row.id,
                name=" ".join(
                    part
                    for part in (row.last_name, row.first_name, row.middle_name)
                    if part
                ),
            )
            for row in rows
        ]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "User data unavailable") from exc


@router.get("/orders", response_model=list[TuitionOrder])
async def orders(
    request: Request,
    response: Response,
    viewer: Viewer,
    student_id: UUID,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    """Финансовая история указанного ученика с проверкой текущего доступа."""
    response.headers["Cache-Control"] = "private, no-store"
    await check_student(request, viewer, student_id)
    return await call(request, "orders", student_id, 50, offset)


@router.post("/payments", response_model=Payment, status_code=202)
async def start(
    request: Request, response: Response, viewer: Viewer, body: CheckoutBody
):
    """Создаёт попытку с UUID плательщика из авторизации, не пользовательского JSON."""
    response.headers["Cache-Control"] = "private, no-store"
    if viewer.role == Role.ADMIN:
        raise HTTPException(403, "Use a student or parent account for checkout")
    student = await check_student(request, viewer, body.student_id)
    if not student.is_active:
        raise HTTPException(409, "Student is inactive")
    if body.period_type == "quarter":
        journal = request.app.state.journal_client
        if journal is None:
            raise HTTPException(503, "Journal unavailable")
        try:
            if await journal.get_current_class_id(student.id) is None:
                raise HTTPException(409, "Student is not enrolled")
        except JournalUnavailableError as exc:
            raise HTTPException(503, "Journal unavailable") from exc
    return await call(
        request, "start", {**body.model_dump(mode="json"), "payer_id": str(viewer.id)}
    )


@router.get("/payments", response_model=list[NamedPayment])
async def payments(
    request: Request,
    response: Response,
    viewer: Admin,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    """Дополняет административную страницу ФИО одним пакетным запросом."""
    return await named_payment_history(request, response, offset)


async def named_payment_history(request: Request, response: Response, offset: int):
    """Общее чтение финансовой истории после проверки права вызывающего."""
    response.headers["Cache-Control"] = "private, no-store"
    rows = [
        Payment.model_validate(row)
        for row in await call(request, "payments", 50, offset)
    ]
    if not rows:
        return []
    try:
        async with request.app.state.uow_factory() as uow:
            users = await uow.users.get_by_ids(list({row.student_id for row in rows}))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "User data unavailable") from exc
    names = {
        user.id: " ".join(
            part for part in (user.last_name, user.first_name, user.middle_name) if part
        )
        for user in users
    }
    return [
        NamedPayment(
            **row.model_dump(),
            student_name=names.get(row.student_id) or "Пользователь недоступен",
        )
        for row in rows
    ]


@router.post("/payments/{payment_id}/refresh", response_model=Payment)
async def refresh(request: Request, response: Response, viewer: Viewer, payment_id: Id):
    """Сверяет только разрешённый платёж, не доверяя знанию его числового ID."""
    response.headers["Cache-Control"] = "private, no-store"
    previous = Payment.model_validate(await call(request, "get_payment", payment_id))
    await check_student(request, viewer, previous.student_id)
    updated = Payment.model_validate(await call(request, "refresh", payment_id))
    if (
        updated.student_id != previous.student_id
        or updated.payer_id != previous.payer_id
    ):
        raise HTTPException(503, "Billing contract mismatch")
    return updated


@router.post("/payments/{payment_id}/refund", response_model=Payment, status_code=202)
async def refund(
    request: Request,
    response: Response,
    viewer: Admin,
    payment_id: Id,
    body: RefundBody,
):
    """Только полный возврат; UUID администратора сохраняется в аудите Billing."""
    response.headers["Cache-Control"] = "private, no-store"
    return await call(
        request,
        "refund",
        payment_id,
        {"actor_id": str(viewer.id), **body.model_dump(mode="json")},
    )


@router.post("/payments/{payment_id}/reconcile", response_model=Payment)
async def reconcile(
    request: Request,
    response: Response,
    viewer: Admin,
    payment_id: Id,
    body: ReconcileBody,
):
    """Admin инициирует проверку провайдера, но не выставляет paid вручную."""
    response.headers["Cache-Control"] = "private, no-store"
    return await call(request, "reconcile", payment_id, body.model_dump(mode="json"))


class WebhookObject(BaseModel):
    """Остальные поля ЮKassa намеренно не используются как доказательство оплаты."""

    model_config = ConfigDict(extra="ignore")
    id: UUID


class WebhookBody(BaseModel):
    """Сигнал сверки известного локальной системе платежа/возврата."""

    model_config = ConfigDict(extra="ignore")
    type: Literal["notification"]
    event: Literal["payment.succeeded", "payment.canceled", "refund.succeeded"]
    object: WebhookObject


@router.post("/yookassa/webhook")
async def webhook(request: Request, body: WebhookBody):
    """Без JWT: подлинность результата определяется собственным GET к провайдеру."""
    await call(
        request, "webhook", {"event": body.event, "object_id": str(body.object.id)}
    )
    return {"accepted": True}
