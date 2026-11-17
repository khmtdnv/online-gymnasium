"""Личные задания учебных документов за служебной границей Gateway."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from document_service.api.documents import (
    CreatedDocumentResponse,
    DocumentStatusResponse,
)
from document_service.api.security import get_creator
from document_service.application.templates import (
    CreateTemplateCommand,
    TemplateConflictError,
    TemplateRequest,
)
from document_service.domain.document import DocumentStatus

router = APIRouter(prefix="/internal/documents", tags=["internal documents"])
Creator = Annotated[UUID, Depends(get_creator)]


def describe(job) -> DocumentStatusResponse:
    """Возвращает только статус, без снимка ФИО и внутреннего ключа MinIO."""
    return DocumentStatusResponse(
        id=job.id,
        document_type=job.document_type,
        status=job.status.value,
        created_at=job.created_at,
        download_url=f"/api/v1/documents/{job.id}/content"
        if job.status == DocumentStatus.COMPLETED
        else None,
    )


def owned_job(request, job_id, creator):
    """Чужое и историческое неразмеченное задание не раскрывает даже свой статус."""
    with request.app.state.uow_factory() as uow:
        job = uow.documents.get_job(job_id)
    if job is None or job.creator_id != creator:
        raise HTTPException(404, "Document not found")
    return job


@router.post("", status_code=202, response_model=CreatedDocumentResponse)
def create(
    body: TemplateRequest, request: Request, response: Response, creator: Creator
):
    """Создаёт асинхронное задание с постоянным ключом запроса создателя."""
    response.headers["Cache-Control"] = "private, no-store"
    command = CreateTemplateCommand(**body.model_dump(), creator_id=creator)
    try:
        with request.app.state.uow_factory() as uow:
            job = uow.documents.create_template_job(command)
    except TemplateConflictError as exc:
        raise HTTPException(409, "Document request key conflict") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Document storage unavailable") from exc
    return CreatedDocumentResponse(
        id=job.id, document_type=job.document_type, status=job.status.value
    )


@router.get(
    "", response_model=list[DocumentStatusResponse], response_model_exclude_none=True
)
def list_jobs(
    request: Request,
    response: Response,
    creator: Creator,
    offset: Annotated[int, Query(ge=0, le=2147483647)] = 0,
):
    """Показывает ограниченную страницу собственных заданий."""
    response.headers["Cache-Control"] = "private, no-store"
    with request.app.state.uow_factory() as uow:
        return [describe(job) for job in uow.documents.list_jobs(creator, 50, offset)]


@router.get(
    "/{job_id}", response_model=DocumentStatusResponse, response_model_exclude_none=True
)
def status(job_id: UUID, request: Request, response: Response, creator: Creator):
    """Читает только своё задание, без автоматической выдачи PDF по чужому UUID."""
    response.headers["Cache-Control"] = "private, no-store"
    return describe(owned_job(request, job_id, creator))


@router.get("/{job_id}/content")
def content(job_id: UUID, request: Request, creator: Creator):
    """Выдаёт готовый PDF с запретом кеширования, не публичную ссылку MinIO."""
    job = owned_job(request, job_id, creator)
    if job.status != DocumentStatus.COMPLETED or not job.object_key:
        raise HTTPException(409, "Document not ready")
    data = request.app.state.storage.read(job.object_key)
    if len(data) > 5 * 1024 * 1024 or not data.startswith(b"%PDF"):
        raise HTTPException(503, "Document content unavailable")
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="document-{job_id}.pdf"',
        },
    )
