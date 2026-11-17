"""Проверка и событие идут вместе; повтор решения не создаёт вторую публикацию."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from homework_service.application.homework_answers import (
    ReviewHomeworkAnswerCommand,
    ReviewHomeworkAnswerHandler,
)
from homework_service.domain.homework import Homework
from homework_service.domain.homework_answer import HomeworkAnswer


def test_review_adds_one_event_and_replay_adds_none():
    moment = datetime(2026, 10, 22, 10, tzinfo=UTC)
    teacher = UUID(int=2)
    homework = Homework(
        id=1,
        issued_lesson_id=1,
        class_id=7,
        subject_id=3,
        author_id=teacher,
        description="Задание",
        manual_due_datetime=moment,
    )
    answer = HomeworkAnswer(
        id=10,
        homework_id=1,
        student_id=UUID(int=1),
        answer_text="Решение",
        idempotency_key="one",
        request_hash="a" * 64,
        submitted_at=moment,
    )
    outbox = SimpleNamespace(add_review_event=AsyncMock())
    unit = SimpleNamespace(
        answers=SimpleNamespace(
            get_by_id=AsyncMock(return_value=answer),
            save_review=AsyncMock(return_value=answer),
        ),
        answer_files=SimpleNamespace(
            has_pending=AsyncMock(return_value=False),
            list_for_answers=AsyncMock(return_value={}),
        ),
        files=SimpleNamespace(get_current_time=AsyncMock(return_value=moment)),
        outbox=outbox,
    )

    @asynccontextmanager
    async def uow():
        yield unit

    async def run():
        handler = ReviewHomeworkAnswerHandler(uow, None, None)
        handler.authorize = AsyncMock(return_value=homework)
        command = ReviewHomeworkAnswerCommand(
            teacher_id=teacher,
            homework_id=1,
            answer_id=10,
            status="graded",
            grade=4,
        )
        assert (await handler.handle(command)).grade == 4
        outbox.add_review_event.assert_awaited_once_with(homework, answer)
        await handler.handle(command)
        assert outbox.add_review_event.await_count == 1
        # Сбой записи события не должен дать успешный ответ об оценке.
        answer.status, answer.grade = "submitted", None
        answer.reviewed_at, answer.reviewer_id = None, None
        outbox.add_review_event.side_effect = RuntimeError("outbox failed")
        with pytest.raises(RuntimeError, match="outbox failed"):
            await handler.handle(command)

    asyncio.run(run())
