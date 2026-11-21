"""Читает и атомарно обновляет управляемые демо-уроки внутри Schedule.

Режимы (JSON на stdin):
- export: уроки окна по классам/учителям с признаком «создан демо-скриптом»;
- apply: атомарно применяет план перестройки (учитель, предмет, время),
  проверяя, что уроки не менялись с момента экспорта;
- teacher_usage: число плановых уроков у каждого преподавателя.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

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
from sqlalchemy import func, select

BUFFER_START = datetime(2030, 1, 1, tzinfo=UTC)
LESSON_MINUTES = 45


def serialize(lesson):
    return {
        "id": lesson.id,
        "class_id": lesson.class_id,
        "teacher_id": str(lesson.teacher_id),
        "subject_id": lesson.subject_id,
        "starts_at": lesson.starts_at.isoformat(),
        "ends_at": lesson.ends_at.isoformat(),
        "version": lesson.version,
    }


async def main():
    data = json.load(sys.stdin)
    engine = create_engine(Settings().database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            if data["mode"] == "export":
                start, end = (
                    datetime.fromisoformat(data["start"]),
                    datetime.fromisoformat(data["end"]),
                )
                class_ids, teacher_ids = (
                    data["class_ids"],
                    [UUID(value) for value in data["teacher_ids"]],
                )
                all_rows = (
                    await session.scalars(
                        select(ScheduledLessonRow).where(
                            ScheduledLessonRow.status == "planned",
                            ScheduledLessonRow.starts_at >= start,
                            ScheduledLessonRow.starts_at < end,
                            (
                                ScheduledLessonRow.class_id.in_(class_ids)
                                | ScheduledLessonRow.teacher_id.in_(teacher_ids)
                            ),
                        )
                    )
                ).all()
                managed_ids = set(
                    (
                        await session.scalars(
                            select(IdempotencyRequestRow.lesson_id).where(
                                IdempotencyRequestRow.operation == "create_lesson",
                                IdempotencyRequestRow.idempotency_key.like(
                                    "demo-expanded-%"
                                )
                                | IdempotencyRequestRow.idempotency_key.like(
                                    "demo-school-%"
                                ),
                                IdempotencyRequestRow.lesson_id.is_not(None),
                            )
                        )
                    ).all()
                )
                result = [
                    {**serialize(row), "managed": row.id in managed_ids}
                    for row in all_rows
                ]
                print(json.dumps(result))
                return
            if data["mode"] == "teacher_usage":
                rows = (
                    await session.execute(
                        select(
                            ScheduledLessonRow.teacher_id,
                            func.count(ScheduledLessonRow.id),
                        )
                        .where(ScheduledLessonRow.status == "planned")
                        .group_by(ScheduledLessonRow.teacher_id)
                    )
                ).all()
                print(json.dumps({str(teacher): count for teacher, count in rows}))
                return
            plan = data["plan"]
            ids = [row["id"] for row in plan]
            rows = (
                await session.scalars(
                    select(ScheduledLessonRow)
                    .where(ScheduledLessonRow.id.in_(ids))
                    .with_for_update()
                )
            ).all()
            actual = {row.id: row for row in rows}
            if len(actual) != len(plan):
                raise ValueError("A planned lesson is missing")
            for entry in plan:
                row = actual[entry["id"]]
                if serialize(row) != entry["before"] or row.status != "planned":
                    raise ValueError("A lesson changed while the plan was prepared")
            # Фаза 1: уникальные буферные учителя и, при смене времени,
            # буферные интервалы в далёком будущем. Временные уникальные
            # значения видны только внутри транзакции и позволяют менять
            # уроки местами, не нарушая ограничения пересечений.
            for index, entry in enumerate(plan):
                row = actual[entry["id"]]
                row.teacher_id = uuid5(NAMESPACE_URL, f"og-demo-buffer-{entry['id']}")
                if entry.get("starts_at") and datetime.fromisoformat(
                    entry["starts_at"]
                ) != datetime.fromisoformat(entry["before"]["starts_at"]):
                    buffer_start = BUFFER_START + timedelta(hours=index)
                    row.starts_at = buffer_start
                    row.ends_at = buffer_start + timedelta(minutes=LESSON_MINUTES)
            await session.flush()
            # Фаза 2: финальные значения, версии и события — согласованно.
            outbox = SqlAlchemyOutboxRepository(session)
            for entry in plan:
                row = actual[entry["id"]]
                row.teacher_id = UUID(entry["teacher_id"])
                if entry.get("subject_id"):
                    row.subject_id = entry["subject_id"]
                if entry.get("starts_at"):
                    row.starts_at = datetime.fromisoformat(entry["starts_at"])
                    row.ends_at = datetime.fromisoformat(entry["ends_at"])
                row.version += 1
                await outbox.add(
                    ScheduleChanged(
                        lesson_id=row.id,
                        class_id=row.class_id,
                        affected_dates=(row.starts_at.date(),),
                    )
                )
                await outbox.add(
                    LessonSnapshot(
                        lesson_id=row.id,
                        class_id=row.class_id,
                        teacher_id=row.teacher_id,
                        subject_id=row.subject_id,
                        starts_at=row.starts_at,
                        ends_at=row.ends_at,
                        status=row.status,
                        version=row.version,
                    )
                )
            await session.flush()
        print(json.dumps({"changed": len(plan)}))
    finally:
        await engine.dispose()


asyncio.run(main())
