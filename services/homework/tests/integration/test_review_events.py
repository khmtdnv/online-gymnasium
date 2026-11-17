"""Настоящая PostgreSQL: результат проверки и событие нельзя сохранить порознь."""

import asyncio

import pytest
from sqlalchemy import func, select

from homework_service.application.homework_answers import (
    ReviewHomeworkAnswerCommand,
    SubmitHomeworkAnswerCommand,
)
from homework_service.domain.homework import Homework
from homework_service.infrastructure.models.outbox_event import HomeworkOutboxEventRow
from tests.integration.test_homework_answers import STUDENT, TEACHER, handlers
from tests.test_domain_homework import data

pytestmark = pytest.mark.integration


def test_review_outbox_is_atomic_and_replay_does_not_duplicate(engine):
    uow, submit, review = handlers(engine)

    async def run():
        async with uow() as unit:
            parent = await unit.homeworks.add(Homework(**data(author_id=TEACHER)))
        first = await submit.handle(
            SubmitHomeworkAnswerCommand(
                student_id=STUDENT,
                homework_id=parent.id,
                answer_text="Секретный текст не должен войти в событие",
                idempotency_key="audit-test",
            )
        )
        command = ReviewHomeworkAnswerCommand(
            teacher_id=TEACHER,
            homework_id=parent.id,
            answer_id=first.answer.id,
            status="graded",
            grade=5,
        )

        # Умираем после flush события, до commit всей транзакции.
        class FailedCommit:
            async def __aenter__(self):
                self.unit = await uow().__aenter__()
                return self.unit

            async def __aexit__(self, kind, error, traceback):
                await self.unit.__aexit__(
                    RuntimeError, RuntimeError("commit failed"), None
                )
                raise RuntimeError("commit failed")

        broken = type(review)(
            FailedCommit, review._journal_reader, review._schedule_reader
        )
        # Проверка авторизации должна читать обычным UoW, не создавать сбой до записи.
        broken.authorize = review.authorize
        with pytest.raises(RuntimeError, match="commit failed"):
            await broken.handle(command)
        async with uow() as unit:
            assert (await unit.answers.get_by_id(first.answer.id)).status == "submitted"
            assert (
                await unit._session.scalar(
                    select(func.count()).select_from(HomeworkOutboxEventRow)
                )
                == 0
            )
        await review.handle(command)
        await review.handle(command)
        async with uow() as unit:
            events = (await unit._session.scalars(select(HomeworkOutboxEventRow))).all()
            assert len(events) == 1
            event = events[0].envelope
            assert event["event_type"] == "homework.answer.reviewed"
            assert event["payload"]["grade"] == 5
            assert event["payload"]["class_id"] == 7
            assert event["actor"] == {"source": "gateway", "id": str(TEACHER)}
            assert "answer_text" not in event["payload"]
            assert "teacher_comment" not in event["payload"]
            assert len(await unit.outbox.get_pending(limit=100)) == 1
        async with uow() as unit:
            await unit.outbox.mark_published(events[0].event_id)
        async with uow() as unit:
            assert await unit.outbox.get_pending(limit=100) == []

    asyncio.run(run())
