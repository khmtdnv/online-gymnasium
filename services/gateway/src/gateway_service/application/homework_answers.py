"""Независимый публичный контракт сдачи и проверки работ в Gateway."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from gateway_service.application.homework_files import (
    HomeworkFileInput,
    _validate_metadata,
)

PositiveId = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Text = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, max_length=10000)
]


class HomeworkAnswerFileResult(BaseModel):
    """Приватное вложение ответа без ключа объекта и отпечатка."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    id: PositiveId
    answer_id: PositiveId
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=10485760)
    content_type: str = Field(min_length=1, max_length=127)
    upload_status: Literal["pending", "ready"]

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """Проверяет безопасное имя и совместимость формата."""
        _validate_metadata(self.file_name, self.content_type)
        return self


class HomeworkAnswerResult(BaseModel):
    """Проверенная попытка с сохранённым решением преподавателя."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: PositiveId
    homework_id: PositiveId
    student_id: UUID
    attempt_number: PositiveId
    answer_text: Text
    status: Literal["submitted", "returned", "graded"]
    submitted_at: AwareDatetime
    grade: int | None = Field(default=None, strict=True, ge=2, le=5)
    teacher_comment: Text = ""
    reviewer_id: UUID | None = None
    reviewed_at: AwareDatetime | None = None
    files: list[HomeworkAnswerFileResult] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """Не пропускает противоречивое состояние либо файлы чужой попытки."""
        if any(file.answer_id != self.id for file in self.files) or len(
            {file.id for file in self.files}
        ) != len(self.files):
            raise ValueError("Invalid answer file relationship")
        if self.status == "submitted":
            valid = (
                self.grade is None
                and self.reviewer_id is None
                and self.reviewed_at is None
                and not self.teacher_comment
            )
        else:
            valid = self.reviewer_id is not None and self.reviewed_at is not None
            valid = valid and (
                self.grade is not None
                if self.status == "graded"
                else self.grade is None and bool(self.teacher_comment)
            )
        if not valid:
            raise ValueError("Invalid answer review state")
        return self


class NamedHomeworkAnswerResult(HomeworkAnswerResult):
    """Добавляет ФИО из базы Gateway, не копируя его в Homework."""

    student_name: str


class TeacherReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_id: PositiveId
    homework_id: PositiveId
    lesson_id: PositiveId
    class_id: PositiveId
    subject_id: PositiveId
    student_id: UUID
    description: str
    status: Literal["submitted", "returned", "graded"]
    submitted_at: AwareDatetime


class TeacherReviewPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TeacherReviewItem]
    next_cursor: int | None


class HomeworkAnswerInput(BaseModel):
    """Текст и выбранные файлы; автор определяется только по access token."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    answer_text: Text = ""
    files: list[HomeworkFileInput] = Field(
        default_factory=list, max_length=5, strict=True
    )

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        """Отклоняет пустую работу без файлов."""
        if not self.answer_text and not self.files:
            raise ValueError("An answer or a file is required")
        return self


class HomeworkAnswerReviewInput(BaseModel):
    """Оценка2–5 либо возврат с объяснением, без подмены преподавателя."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["returned", "graded"]
    grade: int | None = Field(default=None, strict=True, ge=2, le=5)
    teacher_comment: Text = ""

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        """Требует оценку при проверке и комментарий при возврате."""
        if (
            self.status == "graded"
            and self.grade is None
            or self.status == "returned"
            and (self.grade is not None or not self.teacher_comment)
        ):
            raise ValueError("Invalid grade or return comment")
        return self
