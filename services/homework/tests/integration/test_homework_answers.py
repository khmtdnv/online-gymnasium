"""Реальные транзакции: цикл работы и гонка отправки после возврата."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from homework_service.application.homework_answers import (
    HomeworkAnswerConflictError,
    ReviewHomeworkAnswerCommand,
    ReviewHomeworkAnswerHandler,
    SubmitHomeworkAnswerCommand,
    SubmitHomeworkAnswerHandler,
)
from homework_service.application.ports.schedule_reader import LessonInfo
from homework_service.domain.homework import Homework
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from tests.test_domain_homework import data

pytestmark = pytest.mark.integration
STUDENT = UUID(int=1)
TEACHER = UUID(int=2)


def handlers(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    def uow():
        return SqlAlchemyUnitOfWork(sessions)

    async def current(user):
        return 7

    async def assigned(user, class_id):
        return True

    async def lessons(ids):
        return {
            id: LessonInfo(
                id=id,
                class_id=7,
                subject_id=3,
                teacher_id=TEACHER,
                starts_at=datetime(2026, 10, 1, 10, tzinfo=UTC),
                ends_at=datetime(2026, 10, 1, 11, tzinfo=UTC),
                status="planned",
                version=1,
            )
            for id in ids
        }

    readers = (
        uow,
        SimpleNamespace(get_current_class_id=current, is_teacher_assigned=assigned),
        SimpleNamespace(get_lessons=lessons),
    )
    return (
        uow,
        SubmitHomeworkAnswerHandler(*readers),
        ReviewHomeworkAnswerHandler(*readers),
    )


def test_submit_return_resubmit_grade_preserves_history_and_replays(engine):
    uow, submit, review = handlers(engine)

    async def run():
        async with uow() as unit:
            parent = await unit.homeworks.add(Homework(**data(author_id=TEACHER)))

        def command(key, text="Решение"):
            return SubmitHomeworkAnswerCommand(
                student_id=STUDENT,
                homework_id=parent.id,
                answer_text=text,
                idempotency_key=key,
            )

        first = await submit.handle(command("first"))
        assert first.created and first.answer.attempt_number == 1
        repeat = await submit.handle(command("first"))
        assert not repeat.created and repeat.answer.id == first.answer.id
        with pytest.raises(HomeworkAnswerConflictError):
            await submit.handle(command("first", "Иное решение"))
        returned = await review.handle(
            ReviewHomeworkAnswerCommand(
                teacher_id=TEACHER,
                homework_id=parent.id,
                answer_id=first.answer.id,
                status="returned",
                teacher_comment="Исправь задачу2",
            )
        )
        assert returned.status == "returned" and returned.grade is None
        second = await submit.handle(command("second", "Исправленное решение"))
        assert second.answer.attempt_number == 2 and second.answer.id != first.answer.id
        check = ReviewHomeworkAnswerCommand(
            teacher_id=TEACHER,
            homework_id=parent.id,
            answer_id=second.answer.id,
            status="graded",
            grade=5,
        )
        graded = await review.handle(check)
        assert graded.grade == 5 and graded.reviewer_id == TEACHER
        assert (await review.handle(check)).reviewed_at == graded.reviewed_at
        with pytest.raises(HomeworkAnswerConflictError):
            await submit.handle(command("third"))
        async with uow() as unit:
            history = await unit.answers.list_answers(
                parent.id, STUDENT, 50, 0, latest_only=False
            )
            assert [(row.attempt_number, row.status) for row in history] == [
                (2, "graded"),
                (1, "returned"),
            ]

    asyncio.run(run())


def test_parallel_duplicate_submit_creates_one_answer(engine):
    uow, submit, _ = handlers(engine)

    async def run():
        async with uow() as unit:
            parent = await unit.homeworks.add(Homework(**data(author_id=TEACHER)))
        command = SubmitHomeworkAnswerCommand(
            student_id=STUDENT,
            homework_id=parent.id,
            answer_text="Решение",
            idempotency_key="same",
        )
        results = await asyncio.gather(submit.handle(command), submit.handle(command))
        assert len({result.answer.id for result in results}) == 1
        assert sum(result.created for result in results) == 1

    asyncio.run(run())


def test_two_different_retries_after_return_and_competing_reviews_choose_one(engine):
    uow, submit, review = handlers(engine)

    async def run():
        async with uow() as unit:
            parent = await unit.homeworks.add(Homework(**data(author_id=TEACHER)))

        def command(key):
            return SubmitHomeworkAnswerCommand(
                student_id=STUDENT,
                homework_id=parent.id,
                answer_text="Решение",
                idempotency_key=key,
            )

        first = await submit.handle(command("first"))
        await review.handle(
            ReviewHomeworkAnswerCommand(
                teacher_id=TEACHER,
                homework_id=parent.id,
                answer_id=first.answer.id,
                status="returned",
                teacher_comment="Исправь",
            )
        )
        outcomes = await asyncio.gather(
            submit.handle(command("a")),
            submit.handle(command("b")),
            return_exceptions=True,
        )
        winners = [value for value in outcomes if not isinstance(value, Exception)]
        assert (
            len(winners) == 1
            and sum(
                isinstance(value, HomeworkAnswerConflictError) for value in outcomes
            )
            == 1
        )
        attempt = winners[0].answer
        checks = [
            ReviewHomeworkAnswerCommand(
                teacher_id=TEACHER,
                homework_id=parent.id,
                answer_id=attempt.id,
                status="graded",
                grade=grade,
            )
            for grade in (4, 5)
        ]
        outcomes = await asyncio.gather(
            *(review.handle(check) for check in checks), return_exceptions=True
        )
        assert (
            sum(isinstance(value, HomeworkAnswerConflictError) for value in outcomes)
            == 1
        )
        async with uow() as unit:
            history = await unit.answers.list_answers(
                parent.id, STUDENT, 50, 0, latest_only=False
            )
            assert len(history) == 2 and history[0].status == "graded"

    asyncio.run(run())
