from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, StrictInt, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from journal_service.api.dependencies import (
    get_create_class_handler,
    get_list_classes_handler,
)
from journal_service.api.security import RequireServicePermission
from journal_service.application.classes import (
    MAX_CLASS_OFFSET,
    CreateClassCommand,
    CreateClassHandler,
    ListClassesHandler,
    ListClassesQuery,
    LookupClassesHandler,
    LookupClassesQuery,
)

router = APIRouter(prefix="/internal/classes", include_in_schema=False)


class CreateClassRequest(BaseModel):
    """Принимает имя класса и целочисленный год начала обучения."""

    name: str
    study_year: StrictInt


class ClassResponse(BaseModel):
    """Возвращает сохранённый класс без внутренних деталей базы данных."""

    id: int
    name: str
    study_year: int
    created_at: datetime


@router.post(
    "/lookup",
    response_model=list[ClassResponse],
    dependencies=[Depends(RequireServicePermission("classes:read"))],
)
async def lookup_classes(
    body: LookupClassesQuery, request: Request
) -> list[ClassResponse]:
    """Читает названия классов пакетом, не предоставляя вызывающему write-прав."""
    try:
        rows = await LookupClassesHandler(request.app.state.uow_factory).handle(body)
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Journal unavailable") from exc
    return [ClassResponse(**row.model_dump()) for row in rows]


@router.post(
    "",
    response_model=ClassResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireServicePermission("classes:write"))],
)
async def create_class(
    request_model: CreateClassRequest,
    handler: Annotated[CreateClassHandler, Depends(get_create_class_handler)],
) -> ClassResponse:
    """Создаёт класс и возвращает его сохранённые данные.

    Args:
        request_model: Имя класса и целочисленный год начала обучения.
        handler: Обработчик создания класса с отдельной транзакцией.

    Returns:
        Сохранённый класс для HTTP-ответа со статусом 201.
    """
    try:
        command = CreateClassCommand(
            name=request_model.name, study_year=request_model.study_year
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid class data") from exc
    result = await handler.handle(command)

    return ClassResponse(
        id=result.id,
        name=result.name,
        study_year=result.study_year,
        created_at=result.created_at,
    )


@router.get(
    "",
    response_model=list[ClassResponse],
    dependencies=[Depends(RequireServicePermission("classes:read"))],
)
async def list_classes(
    handler: Annotated[ListClassesHandler, Depends(get_list_classes_handler)],
    study_year: Annotated[int | None, Query(ge=1900, le=9998)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=MAX_CLASS_OFFSET)] = 0,
) -> list[ClassResponse]:
    """Возвращает страницу классов с необязательным фильтром по году.

    Args:
        handler: Обработчик чтения классов.
        study_year: Год начала обучения; None отключает фильтр.
        limit: Максимальное количество классов в ответе.
        offset: Количество записей, пропускаемых перед началом страницы.

    Returns:
        Классы в порядке репозитория; пустой список, если записей нет.
    """
    query = ListClassesQuery(study_year=study_year, limit=limit, offset=offset)
    result = await handler.handle(query)

    school_classes = []
    for school_class in result:
        school_classes.append(
            ClassResponse(
                id=school_class.id,
                name=school_class.name,
                study_year=school_class.study_year,
                created_at=school_class.created_at,
            )
        )

    return school_classes
