"""Одна попытка ответа и неизменяемый результат её проверки."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(slots=True)
class HomeworkAnswer:
    """Хранит историю одной сдачи, а не перезаписываемый последний ответ."""

    homework_id: int
    student_id: UUID
    answer_text: str
    idempotency_key: str
    request_hash: str
    attempt_number: int = 1
    id: int | None = None
    status: Literal["submitted", "returned", "graded"] = "submitted"
    submitted_at: datetime | None = None
    grade: int | None = None
    teacher_comment: str = ""
    reviewer_id: UUID | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Не допускает несогласованную оценку, состояние или серверные поля.

        Raises:
            ValueError: Поля попытки нарушают локальные правила.
            TypeError: ID ученика не является UUID.
        """
        for value in (
            self.homework_id,
            self.attempt_number,
            *(() if self.id is None else (self.id,)),
        ):
            if type(value) is not int or not 1 <= value <= 2147483647:
                raise ValueError("Answer IDs and attempt must be positive integers")
        if not isinstance(self.student_id, UUID):
            raise TypeError("Expected student UUID")
        if (
            not isinstance(self.answer_text, str)
            or len(self.answer_text) > 10000
            or self.answer_text != self.answer_text.strip()
        ):
            raise ValueError("Expected normalized answer text")
        if (
            re.fullmatch(r"[!-~]{1,128}", self.idempotency_key) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.request_hash) is None
        ):
            raise ValueError("Invalid request identity")
        for timestamp in (self.submitted_at, self.reviewed_at):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("Expected timezone-aware timestamps")
        if (
            not isinstance(self.teacher_comment, str)
            or len(self.teacher_comment) > 10000
            or self.teacher_comment != self.teacher_comment.strip()
        ):
            raise ValueError("Invalid review comment")
        if self.status == "submitted":
            valid = (
                self.grade is None
                and self.reviewer_id is None
                and self.reviewed_at is None
                and self.teacher_comment == ""
            )
        else:
            valid = (
                isinstance(self.reviewer_id, UUID)
                and self.reviewed_at is not None
                and (
                    self.status == "returned"
                    and self.grade is None
                    and bool(self.teacher_comment)
                    or self.status == "graded"
                    and type(self.grade) is int
                    and 2 <= self.grade <= 5
                )
            )
        if not valid:
            raise ValueError("Review fields do not match the answer status")
