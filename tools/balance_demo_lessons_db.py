"""Reads, wipes and bulk-inserts the managed demo lessons inside Schedule.

Modes (JSON on stdin):
- export: lessons of a window by classes/teachers with a "created by the
  demo script" flag;
- apply: atomically applies a rebuild plan (teacher, subject, time),
  checking that the lessons did not change since the export;
- teacher_usage: planned lesson count of every teacher;
- wipe: input {"class_ids": [...]} - deletes every lesson of the given
  demo classes in one transaction - the id rows are collected by class
  first (off-grid seed rows carry no idempotency keys), then their key
  rows go (the foreign key has no cascade), then the lessons; Redis
  day-cache keys are dropped after the commit. No events are emitted;
- create: input {"study_year": 2026, "plan": [{"class_id", "subject_id",
  "teacher_id", "date", "period"}, ...]} - inserts the whole study-year
  plan in class-week chunks, one transaction per chunk - lesson rows
  with version=1, ScheduleChanged + LessonSnapshot events and
  idempotency rows demo-year-<year>-<class_id>-<date>-<period> with
  operation='create_lesson' and the request hash of the create-lesson
  API path. A failed chunk rolls back only itself and stops the run
  with the list of unfinished chunks; a rerun skips completed chunks by
  the presence of their keys.

The script runs inside the schedule-api container (see run_db in
tools/rebuild_demo_timetable.py); service imports are deferred, so the
pure planning helpers stay importable outside the container for tests.
"""

import asyncio
import hashlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from schedule_service.domain.events import LessonSnapshot, ScheduleChanged
from schedule_service.domain.school_periods import PERIODS, TIMEZONE

BUFFER_START = datetime(2030, 1, 1, tzinfo=UTC)
LESSON_MINUTES = 45

# LIKE patterns of the idempotency keys that mark lessons managed by the
# demo tools; export and the repair path recognize a lesson by them.
MANAGED_KEY_PREFIXES = ("demo-year-%", "demo-expanded-%", "demo-school-%")

# Idempotency operation of the lesson-creation API path.
CREATE_LESSON_OPERATION = "create_lesson"

# Batch size of IN () statements: PostgreSQL binds at most 65535
# parameters, so the wipe of a whole study year never sends one huge list.
SQL_BATCH_SIZE = 1000


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


# ------------------------------------------------- pure plan helpers


def year_idempotency_key(study_year: int, class_id: int, day: date, period: int) -> str:
    """Builds the managed key of one year-plan lesson."""
    return f"demo-year-{study_year}-{class_id}-{day.isoformat()}-{period}"


def day_cache_key(class_id: int, day: date) -> str:
    """Builds the Redis day-cache key of a class schedule."""
    return f"schedule:v2:class:{class_id}:date:{day.isoformat()}"


def lesson_interval(day: date, period: int) -> tuple[datetime, datetime]:
    """Returns the exact period bounds of a lesson in school time."""
    if not 1 <= period <= len(PERIODS):
        raise ValueError(f"period {period} leaves the {len(PERIODS)}-period grid")
    start = datetime.combine(day, PERIODS[period - 1].start_at, TIMEZONE)
    end = datetime.combine(day, PERIODS[period - 1].end_at, TIMEZONE)
    return start, end


def canonical_lesson_body(entry: dict) -> dict:
    """Builds the exact request body the create-lesson API hashes.

    Mirrors CreateLessonRequest.model_dump(mode="json"): the same field
    set, the teacher as a lowercase UUID string and the interval bounds
    as ISO strings in school time (+05:00 round-trips through pydantic
    unchanged, so the hash equals the API-path hash).
    """
    return {
        "class_id": int(entry["class_id"]),
        "teacher_id": str(UUID(entry["teacher_id"])),
        "subject_id": int(entry["subject_id"]),
        "starts_at": entry["starts_at"].isoformat(),
        "ends_at": entry["ends_at"].isoformat(),
    }


def lesson_request_hash(entry: dict) -> str:
    """Computes the request hash exactly like the create-lesson API."""
    serialized = json.dumps(
        canonical_lesson_body(entry), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def prepare_entry(raw: dict, study_year: int) -> dict:
    """Validates one plan entry and derives its time, key and hash."""
    day = date.fromisoformat(raw["date"])
    period = int(raw["period"])
    starts_at, ends_at = lesson_interval(day, period)
    entry = {
        "class_id": int(raw["class_id"]),
        "subject_id": int(raw["subject_id"]),
        "teacher_id": str(UUID(raw["teacher_id"])),
        "date": day,
        "period": period,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    entry["key"] = year_idempotency_key(study_year, entry["class_id"], day, period)
    entry["request_hash"] = lesson_request_hash(entry)
    return entry


def build_chunks(plan: list[dict], study_year: int) -> list[dict]:
    """Groups the year plan into class-week chunks in a stable order.

    Every chunk holds the entries of one class of one Monday-based week
    sorted by (date, period), their idempotency keys and its own
    identity for reports. Duplicate keys reject the whole plan: one
    class-day-period slot must carry exactly one lesson.
    """
    by_chunk: dict[tuple[int, date], list[dict]] = {}
    seen_keys: set[str] = set()
    duplicate_keys: set[str] = set()
    for raw in plan:
        entry = prepare_entry(raw, study_year)
        if entry["key"] in seen_keys:
            duplicate_keys.add(entry["key"])
        seen_keys.add(entry["key"])
        week_start = entry["date"] - timedelta(days=entry["date"].weekday())
        by_chunk.setdefault((entry["class_id"], week_start), []).append(entry)
    if duplicate_keys:
        raise ValueError(f"duplicate plan lessons for keys {sorted(duplicate_keys)}")
    chunks = []
    for (class_id, week_start), entries in sorted(by_chunk.items()):
        entries.sort(key=lambda item: (item["date"], item["period"]))
        chunks.append(
            {
                "class_id": class_id,
                "week_start": week_start,
                "entries": entries,
                "keys": [entry["key"] for entry in entries],
            }
        )
    return chunks


def describe_chunk(chunk: dict) -> dict:
    """Returns the report identity of a chunk."""
    return {
        "class_id": chunk["class_id"],
        "week_start": chunk["week_start"].isoformat(),
    }


def lesson_events(lesson: dict) -> list:
    """Builds the ScheduleChanged + LessonSnapshot pair of a new lesson.

    The field order and values mirror the create-lesson API path: one
    cache-invalidation event with the local lesson date and one snapshot
    with version=1.
    """
    return [
        ScheduleChanged(
            lesson_id=lesson["id"],
            class_id=lesson["class_id"],
            affected_dates=(lesson["starts_at"].date(),),
        ),
        LessonSnapshot(
            lesson_id=lesson["id"],
            class_id=lesson["class_id"],
            teacher_id=UUID(lesson["teacher_id"]),
            subject_id=lesson["subject_id"],
            starts_at=lesson["starts_at"],
            ends_at=lesson["ends_at"],
            status=lesson["status"],
            version=lesson["version"],
        ),
    ]


def outbox_row(event) -> dict:
    """Serializes one event exactly as the outbox repository writes it.

    Must stay in sync with
    schedule_service.infrastructure.outbox_repository.SqlAlchemyOutboxRepository.add.
    """
    if isinstance(event, ScheduleChanged):
        return {
            "event_type": "schedule.changed",
            "payload": {
                "lesson_id": event.lesson_id,
                "class_id": event.class_id,
                "affected_dates": [day.isoformat() for day in event.affected_dates],
            },
        }
    if isinstance(event, LessonSnapshot):
        return {
            "event_type": "lesson.snapshot",
            "payload": {
                "lesson_id": event.lesson_id,
                "class_id": event.class_id,
                "teacher_id": str(event.teacher_id),
                "subject_id": event.subject_id,
                "starts_at": event.starts_at.isoformat(),
                "ends_at": event.ends_at.isoformat(),
                "status": event.status,
                "version": event.version,
            },
        }
    raise TypeError(f"Unsupported outbox event: {type(event).__name__}")


def in_batches(values, size: int = SQL_BATCH_SIZE):
    """Yields the values in batches of at most size, order preserved."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


# ------------------------------------------------- wipe and create runs


async def run_wipe(store_factory, session_factory, cache, class_ids) -> dict:
    """Deletes all lessons of the classes in one transaction, then cache.

    The order is fixed: collect the ids of every lesson of the classes
    (off-grid seed lessons have no keys and are still wiped), delete the
    idempotency rows of those lessons (the foreign key has no cascade),
    delete the lessons, commit - only then drop the day-cache keys of
    the wiped class-dates in Redis. No outbox events are emitted.
    """
    async with session_factory() as session, session.begin():
        store = store_factory(session)
        rows = await store.lessons_of_classes(class_ids)
        lesson_ids = [row[0] for row in rows]
        class_days = {(row[1], row[2].astimezone(TIMEZONE).date()) for row in rows}
        deleted_keys = await store.delete_idempotency_for_lessons(lesson_ids)
        deleted_lessons = await store.delete_lessons(lesson_ids)
    deleted_cache = await cache.delete_day_cache(class_days)
    return {
        "lessons": deleted_lessons,
        "idempotency_keys": deleted_keys,
        "cache_keys": deleted_cache,
    }


async def run_create(store_factory, session_factory, chunks: list[dict]) -> dict:
    """Inserts the chunks one transaction per chunk, stopping on failure.

    A chunk whose keys all exist is skipped (completed by an earlier
    run). Any chunk error rolls back only that chunk, the run stops and
    the report lists the failed and remaining chunks for a rerun.
    """
    inserted = 0
    inserted_chunks = 0
    skipped_chunks = 0
    failed_chunk = None
    unfinished: list[dict] = []
    for index, chunk in enumerate(chunks):
        try:
            async with session_factory() as session, session.begin():
                store = store_factory(session)
                existing = await store.existing_keys(chunk["keys"])
                if existing == set(chunk["keys"]):
                    skipped_chunks += 1
                    continue
                await store.insert_chunk(chunk)
            inserted += len(chunk["entries"])
            inserted_chunks += 1
        except Exception as error:  # noqa: BLE001 - reported, not raised
            failed_chunk = {**describe_chunk(chunk), "error": str(error)}
            unfinished = [describe_chunk(item) for item in chunks[index:]]
            break
    return {
        "inserted": inserted,
        "chunks_total": len(chunks),
        "chunks_inserted": inserted_chunks,
        "chunks_skipped": skipped_chunks,
        "failed_chunk": failed_chunk,
        "unfinished_chunks": unfinished,
    }


# ------------------------------------------------- container bindings


class SqlLessonStore:
    """All wipe/create SQL of the tool against one open session.

    The service rows are imported on construction: the module stays
    importable outside the schedule container (unit tests run without
    SQLAlchemy and drive the runs with fakes).
    """

    def __init__(self, session) -> None:
        from schedule_service.infrastructure.models.idempotency_request import (
            IdempotencyRequestRow,
        )
        from schedule_service.infrastructure.models.outbox_event import OutboxEventRow
        from schedule_service.infrastructure.models.scheduled_lesson import (
            ScheduledLessonRow,
        )

        self._session = session
        self._lesson_row = ScheduledLessonRow
        self._key_row = IdempotencyRequestRow
        self._event_row = OutboxEventRow

    async def lessons_of_classes(self, class_ids):
        """Rows (id, class_id, starts_at) of every lesson of the classes."""
        from sqlalchemy import select

        statement = select(
            self._lesson_row.id,
            self._lesson_row.class_id,
            self._lesson_row.starts_at,
        ).where(self._lesson_row.class_id.in_(class_ids))
        rows = (await self._session.execute(statement)).all()
        return [(row[0], row[1], row[2]) for row in rows]

    async def delete_idempotency_for_lessons(self, lesson_ids) -> int:
        """Deletes the key rows of the lessons before the lessons go."""
        from sqlalchemy import delete

        if not lesson_ids:
            return 0
        removed = 0
        for batch in in_batches(lesson_ids):
            statement = delete(self._key_row).where(self._key_row.lesson_id.in_(batch))
            removed += (await self._session.execute(statement)).rowcount or 0
        return removed

    async def delete_lessons(self, lesson_ids) -> int:
        """Deletes the lesson rows themselves."""
        from sqlalchemy import delete

        if not lesson_ids:
            return 0
        removed = 0
        for batch in in_batches(lesson_ids):
            statement = delete(self._lesson_row).where(self._lesson_row.id.in_(batch))
            removed += (await self._session.execute(statement)).rowcount or 0
        return removed

    async def existing_keys(self, keys) -> set[str]:
        """Returns the create-lesson keys that already exist."""
        from sqlalchemy import select

        if not keys:
            return set()
        statement = select(self._key_row.idempotency_key).where(
            self._key_row.operation == CREATE_LESSON_OPERATION,
            self._key_row.idempotency_key.in_(keys),
        )
        return set((await self._session.scalars(statement)).all())

    async def insert_chunk(self, chunk: dict) -> None:
        """Inserts every entry of the chunk in the open transaction."""
        for entry in chunk["entries"]:
            await self.add_lesson(entry)

    async def add_lesson(self, entry: dict) -> None:
        """Inserts one lesson with its events and key row.

        The order mirrors the API path: claim the key, insert the lesson
        with version=1, emit the event pair, then complete the key with
        the created lesson id. A duplicate key aborts the whole chunk
        transaction through the unique constraint.
        """
        claim = self._key_row(
            operation=CREATE_LESSON_OPERATION,
            idempotency_key=entry["key"],
            request_hash=entry["request_hash"],
        )
        self._session.add(claim)
        await self._session.flush()
        row = self._lesson_row(
            class_id=entry["class_id"],
            teacher_id=UUID(entry["teacher_id"]),
            subject_id=entry["subject_id"],
            starts_at=entry["starts_at"],
            ends_at=entry["ends_at"],
            status="planned",
            version=1,
        )
        self._session.add(row)
        await self._session.flush()
        for event in lesson_events(
            {
                "id": row.id,
                "class_id": row.class_id,
                "teacher_id": str(row.teacher_id),
                "subject_id": row.subject_id,
                "starts_at": row.starts_at,
                "ends_at": row.ends_at,
                "status": row.status,
                "version": row.version,
            }
        ):
            serialized = outbox_row(event)
            self._session.add(
                self._event_row(
                    event_type=serialized["event_type"],
                    payload=serialized["payload"],
                )
            )
        claim.lesson_id = row.id


class RedisDayCache:
    """Drops day-cache keys of class-dates in Redis."""

    def __init__(self, client) -> None:
        self._client = client

    async def delete_day_cache(self, class_days) -> int:
        """Deletes schedule:v2:class:{id}:date:{date} keys; returns count."""
        keys = [
            day_cache_key(class_id, day)
            for class_id, day in sorted(class_days, key=lambda item: (item[0], item[1]))
        ]
        if not keys:
            return 0
        return int(await self._client.delete(*keys))

    async def aclose(self) -> None:
        """Closes the underlying client connection."""
        await self._client.aclose()


def make_day_cache(redis_url: str) -> RedisDayCache:
    """Builds the Redis day-cache client from the service settings."""
    import redis.asyncio as redis

    return RedisDayCache(redis.from_url(redis_url))


async def main():
    from schedule_service.config import Settings
    from schedule_service.infrastructure.database import (
        create_engine,
        create_session_factory,
    )
    from schedule_service.infrastructure.models.idempotency_request import (
        IdempotencyRequestRow,
    )
    from schedule_service.infrastructure.models.scheduled_lesson import (
        ScheduledLessonRow,
    )
    from schedule_service.infrastructure.outbox_repository import (
        SqlAlchemyOutboxRepository,
    )
    from sqlalchemy import func, or_, select

    data = json.load(sys.stdin)
    settings = Settings()
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    try:
        if data["mode"] == "wipe":
            cache = make_day_cache(settings.redis_url)
            try:
                result = await run_wipe(
                    SqlLessonStore,
                    sessions,
                    cache,
                    data["class_ids"],
                )
            finally:
                await cache.aclose()
            print(json.dumps(result))
            return
        if data["mode"] == "create":
            chunks = build_chunks(data["plan"], data["study_year"])
            result = await run_create(SqlLessonStore, sessions, chunks)
            print(json.dumps(result))
            if result["failed_chunk"] is not None:
                # the report is already printed; a non-zero exit tells the
                # orchestrator's run_db that the year is incomplete
                raise SystemExit(1)
            return
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
                                or_(
                                    *(
                                        IdempotencyRequestRow.idempotency_key.like(
                                            pattern
                                        )
                                        for pattern in MANAGED_KEY_PREFIXES
                                    )
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


if __name__ == "__main__":
    asyncio.run(main())
