"""Учебные документы сотрудников: владелец из JWT, квитанция из Billing."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from gateway_service.api.security import RequireRoles
from gateway_service.application.auth import GetCurrentUserResult
from gateway_service.application.billing import Payment
from gateway_service.application.documents import (
    CreatedDocument,
    CreateDocumentBody,
    DocumentJob,
)
from gateway_service.domain.user import Role
from gateway_service.infrastructure.billing_client import BillingRequestError
from gateway_service.infrastructure.document_client import DocumentRequestError

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
Admin = Annotated[GetCurrentUserResult, Depends(RequireRoles((Role.ADMIN,)))]


async def call(request, action, *args):
    """Не раскрывает внутренние URL/traceback и не подменяет сбой пустыми данными."""
    client = request.app.state.documents_client
    if client is None:
        raise HTTPException(503, "Documents unavailable")
    try:
        return await getattr(client, action)(*args)
    except DocumentRequestError as exc:
        raise HTTPException(
            exc.status,
            "Document request failed",
            headers={"Cache-Control": "private, no-store"},
        ) from exc


@router.post("", response_model=CreatedDocument, status_code=202)
async def create(
    body: CreateDocumentBody, request: Request, response: Response, admin: Admin
):
    """Собирает квитанцию по проверенному платежу, остальные образцы по форме."""
    response.headers["Cache-Control"] = "private, no-store"
    data = body.model_dump(mode="json", exclude_none=True)
    if body.document_type == "receipt":
        billing = request.app.state.billing_client
        if billing is None:
            raise HTTPException(503, "Billing unavailable")
        try:
            payment = Payment.model_validate(
                await billing.get_payment(body.payload.payment_id)
            )
            if payment.status != "succeeded":
                raise HTTPException(409, "Receipt requires confirmed payment")
            async with request.app.state.uow_factory() as uow:
                student = await uow.users.get_by_id(payment.student_id)
            if student is None:
                raise HTTPException(503, "Student details unavailable")
            data["payload"] = {
                "payment_id": payment.id,
                "student_full_name": " ".join(
                    part
                    for part in (
                        student.last_name,
                        student.first_name,
                        student.middle_name,
                    )
                    if part
                ),
                "study_month": payment.study_month.isoformat(),
                "period_type": payment.period_type,
                "amount_kopecks": payment.amount_kopecks,
                "currency": "RUB",
            }
        except BillingRequestError as exc:
            raise HTTPException(exc.status, "Billing unavailable") from exc
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Student details unavailable") from exc
    return await call(request, "create", admin.id, data)


@router.get("", response_model=list[DocumentJob], response_model_exclude_none=True)
async def jobs(
    request: Request,
    response: Response,
    admin: Admin,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    """Страница собственных заданий сотрудника, без общей базы чужих ФИО."""
    response.headers["Cache-Control"] = "private, no-store"
    return await call(request, "list_jobs", admin.id, offset)


@router.get("/{job_id}", response_model=DocumentJob, response_model_exclude_none=True)
async def status(job_id: UUID, request: Request, response: Response, admin: Admin):
    """UUID не является паролем: Documents проверит автора по служебному заголовку."""
    response.headers["Cache-Control"] = "private, no-store"
    return await call(request, "get_job", admin.id, job_id)


@router.get("/{job_id}/content")
async def content(job_id: UUID, request: Request, admin: Admin):
    """PDF приходит через JWT-авторизованный запрос, не через публичный MinIO URL."""
    data = await call(request, "content", admin.id, job_id)
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="document-{job_id}.pdf"',
        },
    )
