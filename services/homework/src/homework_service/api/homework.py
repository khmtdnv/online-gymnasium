"""Закрытая выдача ДЗ от проверенного Gateway."""

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy.exc import SQLAlchemyError

from homework_service.api.dependencies import (
    get_create_homework_handler,
    require_gateway,
)
from homework_service.api.errors import HomeworkHTTPError, unavailable
from homework_service.application.homework import (
    CreateHomeworkCommand,
    CreateHomeworkHandler,
    Description,
    HomeworkResult,
    PositiveId,
)
from homework_service.application.homework_files import HomeworkFileInput
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkAlreadyExistsError,
    InvalidHomeworkDataError,
    LessonNotFoundError,
    OwnerLookupUnavailableError,
)

router = APIRouter(
    prefix="/internal", dependencies=[Depends(require_gateway)], include_in_schema=False
)


class CreateHomeworkRequest(BaseModel):
    """Описание и один срок без возможности подменить автора или класс."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    description: Description
    due_lesson_id: PositiveId | None = None
    manual_due_datetime: AwareDatetime | None = None
    files: list[HomeworkFileInput] = Field(
        default_factory=list, max_length=5, strict=True
    )

    @field_validator("manual_due_datetime", mode="before")
    @classmethod
    def validate_iso_deadline(cls, value: object) -> datetime | None:
        """Не подменяет JSON ISO-дату неявным Unix timestamp.

        Args:
            value: Строка даты либо уже разобранное datetime.

        Returns:
            Дата для последующей проверки часового смещения.

        Raises:
            ValueError: Значение не соответствует контракту даты.
        """
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        if value is None or isinstance(value, datetime):
            return value
        raise ValueError("Expected an ISO datetime with timezone")

    @model_validator(mode="after")
    def validate_due_mode(self) -> Self:
        """Отклоняет два срока или отсутствие обоих до вызова сценария."""
        if (self.due_lesson_id is None) == (self.manual_due_datetime is None):
            raise ValueError("Exactly one due mode is required")
        return self


@router.post(
    "/lessons/{lesson_id}/homework", status_code=201, response_model=HomeworkResult
)
async def create_homework(
    lesson_id: Annotated[int, Path(ge=1, le=2147483647)],
    body: CreateHomeworkRequest,
    teacher_id: Annotated[UUID, Header(alias="X-Teacher-ID")],
    handler: Annotated[CreateHomeworkHandler, Depends(get_create_homework_handler)],
) -> HomeworkResult:
    """Вызывает готовый сценарий с доверенным автором и проверенным телом.

    Args:
        lesson_id: Урок выдачи из адреса.
        body: Описание и выбранный срок.
        teacher_id: UUID пользователя, проверенного Gateway.
        handler: Сценарий с readers владельцев и своей транзакцией.

    Returns:
        Сохранённое задание с серверными полями.

    Raises:
        HomeworkHTTPError: Безопасный бизнес-отказ или недоступность зависимостей.
    """
    command = CreateHomeworkCommand(
        teacher_id=teacher_id, issued_lesson_id=lesson_id, **body.model_dump()
    )
    try:
        return await handler.handle(command)
    except HomeworkAccessDeniedError as exc:
        raise HomeworkHTTPError(403, "access_denied", "Access denied") from exc
    except LessonNotFoundError as exc:
        raise HomeworkHTTPError(404, "lesson_not_found", "Lesson not found") from exc
    except HomeworkAlreadyExistsError as exc:
        raise HomeworkHTTPError(
            409, "homework_already_exists", "Homework already exists"
        ) from exc
    except InvalidHomeworkDataError as exc:
        raise HomeworkHTTPError(
            422, "invalid_homework_data", "Invalid homework data"
        ) from exc
    except (OwnerLookupUnavailableError, SQLAlchemyError, OSError) as exc:
        raise unavailable() from exc
