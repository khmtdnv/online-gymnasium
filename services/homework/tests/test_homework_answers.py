"""Ключевые локальные правила сдачи и проверки, без копии матрицы вложений."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from homework_service.application.homework_answers import (
    ReviewHomeworkAnswerCommand,
    SubmitHomeworkAnswerCommand,
)


def test_empty_answer_requires_a_file_and_unknown_identity_is_rejected():
    values = {
        "student_id": UUID(int=1),
        "homework_id": 1,
        "idempotency_key": "attempt-1",
    }
    with pytest.raises(ValidationError):
        SubmitHomeworkAnswerCommand(**values, answer_text=" \n ")
    command = SubmitHomeworkAnswerCommand(**values, answer_text="  Решение  ")
    assert command.answer_text == "Решение"
    with pytest.raises(ValidationError):
        SubmitHomeworkAnswerCommand(**values, answer_text="x", grade=5)


@pytest.mark.parametrize(
    "status,grade,comment",
    [
        ("graded", 1, ""),
        ("graded", True, ""),
        ("returned", None, " "),
        ("returned", 5, "Исправь"),
    ],
)
def test_review_rejects_invalid_grade_or_missing_return_comment(status, grade, comment):
    with pytest.raises(ValidationError):
        ReviewHomeworkAnswerCommand(
            teacher_id=UUID(int=2),
            homework_id=1,
            answer_id=1,
            status=status,
            grade=grade,
            teacher_comment=comment,
        )
