"""Настоящий JOIN последних попыток и пагинация смешанных сроков."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from homework_service.application.homework_list import (
    ListMyHomeworkHandler,
    ListMyHomeworkQuery,
)
from homework_service.application.ports.schedule_reader import LessonInfo
from homework_service.infrastructure.models.homework import HomeworkRow
from homework_service.infrastructure.models.homework_answer import HomeworkAnswerRow
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


def test_period_selects_latest_attempt_then_filters_and_paginates(engine):
    async def run():
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        moment = datetime(2026, 10, 21, tzinfo=UTC)
        student, teacher = UUID(int=1), UUID(int=2)
        async with sessions.begin() as session:
            for id in range(1, 53):
                session.add(
                    HomeworkRow(
                        issued_lesson_id=id,
                        class_id=7,
                        subject_id=1,
                        author_id=teacher,
                        description="Пример",
                        due_lesson_id=999 if id == 52 else None,
                        manual_due_datetime=None
                        if id == 52
                        else moment + timedelta(minutes=60 - id),
                        created_at=moment,
                    )
                )
            await session.flush()
            for id in range(1, 52):
                for attempt, status, grade in [(1, "graded", 4), (2, "returned", None)]:
                    session.add(
                        HomeworkAnswerRow(
                            homework_id=id,
                            student_id=student,
                            answer_text="Ответ",
                            idempotency_key=f"{id}-{attempt}",
                            request_hash="a" * 64,
                            attempt_number=attempt,
                            status=status,
                            grade=grade,
                            teacher_comment="Исправьте",
                            reviewer_id=teacher,
                            submitted_at=moment,
                            reviewed_at=moment,
                        )
                    )
        calendar = SimpleNamespace(
            list_calendar_lessons=AsyncMock(
                return_value=[
                    LessonInfo(
                        id=999,
                        class_id=7,
                        subject_id=1,
                        teacher_id=teacher,
                        starts_at=moment,
                        ends_at=moment + timedelta(hours=1),
                        status="canceled",
                        version=2,
                    )
                ]
            )
        )
        handler = ListMyHomeworkHandler(
            lambda: SqlAlchemyUnitOfWork(sessions),
            SimpleNamespace(get_current_class_id=AsyncMock(return_value=7)),
            calendar,
        )
        query = ListMyHomeworkQuery(
            student_id=student,
            date_from=date(2026, 10, 19),
            date_to=date(2026, 10, 25),
            state="returned",
            limit=50,
            offset=50,
        )
        page = await handler.handle(query)
        assert page.total == 51 and [row.id for row in page.items] == [1]
        assert (
            page.items[0].latest_answer_status == "returned"
            and page.items[0].grade is None
        )
        page = await handler.handle(
            query.model_copy(update={"state": "all", "offset": 50})
        )
        assert page.total == 52 and page.items[-1].id == 52
        assert (
            page.items[-1].due_status == "lesson_cancelled"
            and page.items[-1].final_due_datetime is None
        )
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            assert [row.id for row in await uow.homeworks.list_for_lesson(999)] == [52]

    asyncio.run(run())
