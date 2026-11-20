"""Запускается внутри Schedule: исправляет только неизменённые уроки демо-скриптов."""

import asyncio
import json
import sys
from uuid import UUID

from schedule_service.config import Settings
from schedule_service.domain.events import LessonSnapshot, ScheduleChanged
from schedule_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from schedule_service.infrastructure.models.idempotency_request import (
    IdempotencyRequestRow,
)
from schedule_service.infrastructure.models.scheduled_lesson import ScheduledLessonRow
from schedule_service.infrastructure.outbox_repository import SqlAlchemyOutboxRepository
from sqlalchemy import select


async def main():
    config = json.load(sys.stdin)
    mapping = {
        (item["class_id"], item["subject_id"]): (
            UUID(item["old_teacher_id"]),
            UUID(item["teacher_id"]),
        )
        for item in config
    }
    engine = create_engine(Settings().database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            result = await session.scalars(
                select(ScheduledLessonRow)
                .join(
                    IdempotencyRequestRow,
                    IdempotencyRequestRow.lesson_id == ScheduledLessonRow.id,
                )
                .where(IdempotencyRequestRow.operation == "create_lesson")
                .where(
                    IdempotencyRequestRow.idempotency_key.like("demo-expanded-%")
                    | IdempotencyRequestRow.idempotency_key.like("demo-school-%")
                )
                .with_for_update(of=ScheduledLessonRow)
            )
            outbox = SqlAlchemyOutboxRepository(session)
            changed = 0
            skipped = 0
            seen = set()
            for lesson in result:
                if lesson.id in seen:
                    continue
                seen.add(lesson.id)
                target = mapping.get((lesson.class_id, lesson.subject_id))
                if not target or lesson.teacher_id == target[1]:
                    continue
                if lesson.teacher_id != target[0] or lesson.version != 1:
                    skipped += 1
                    continue
                lesson.teacher_id = target[1]
                lesson.version += 1
                await outbox.add(
                    ScheduleChanged(
                        lesson_id=lesson.id,
                        class_id=lesson.class_id,
                        affected_dates=(lesson.starts_at.date(),),
                    )
                )
                await outbox.add(
                    LessonSnapshot(
                        lesson_id=lesson.id,
                        class_id=lesson.class_id,
                        teacher_id=lesson.teacher_id,
                        subject_id=lesson.subject_id,
                        starts_at=lesson.starts_at,
                        ends_at=lesson.ends_at,
                        status=lesson.status,
                        version=lesson.version,
                    )
                )
                changed += 1
            await session.flush()
        print(json.dumps({"changed": changed, "skipped": skipped}))
    finally:
        await engine.dispose()


asyncio.run(main())
