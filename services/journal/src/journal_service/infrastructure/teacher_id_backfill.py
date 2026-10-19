from uuid import UUID

from sqlalchemy.engine import Connection


def backfill_lesson_teacher_ids(
    bind: Connection,
    mapping: dict[int, UUID],
) -> None:
    raise NotImplementedError("Implement the lesson teacher ID backfill")
