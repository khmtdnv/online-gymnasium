"""Wipes the demo homework scenarios inside the Homework database.

Runs in the homework-api container (the run_db pattern of
tools/rebuild_demo_timetable.py: docker compose exec homework-api
/app/.venv/bin/python -c <source> with JSON on stdin):

    {"mode": "wipe", "teacher_ids": ["<uuid>", ...], "class_ids": [1, ...]}

Deletes the demo assignments - homework of demo teachers (the accounts
of tools/expand_demo_school.py, *@demo.og.test) to demo classes - with
their answers and file links in one transaction, printing the counters.
MinIO objects are not touched: the existing orphan cleaner
(homework_service.cleanup_files) removes unused binaries later. The
public Homework API is not extended - it has no delete operations and
gets none for the demo tool.

Service imports are deferred, so the module stays importable outside
the container for unit tests.
"""

import asyncio
import json
import sys
from uuid import UUID

# Batch size of IN () statements (see balance_demo_lessons_db.py).
SQL_BATCH_SIZE = 1000


def in_batches(values, size: int = SQL_BATCH_SIZE):
    """Yields the values in batches of at most size, order preserved."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


def parse_teachers(raw) -> list[UUID]:
    """Validates the demo teacher ids of the input."""
    return [UUID(value) for value in raw]


def parse_classes(raw) -> list[int]:
    """Validates the demo class ids of the input."""
    return [int(value) for value in raw]


async def run_wipe(store_factory, session_factory, teacher_ids, class_ids) -> dict:
    """Deletes the demo scenarios with their answers and file links.

    One transaction, children first: answer files, answers, homework
    files, then the assignments themselves. The selection is the demo
    scope only - an assignment whose author is a demo teacher AND whose
    class is a demo class; everything else stays. A rerun finds nothing
    and reports zeroes.
    """
    async with session_factory() as session, session.begin():
        store = store_factory(session)
        homework_ids = await store.demo_homework_ids(teacher_ids, class_ids)
        answer_files = await store.delete_answer_files(homework_ids)
        answers = await store.delete_answers(homework_ids)
        files = await store.delete_files(homework_ids)
        assignments = await store.delete_assignments(homework_ids)
    return {
        "assignments": assignments,
        "answers": answers,
        "answer_files": answer_files,
        "files": files,
    }


class SqlScenarioStore:
    """All wipe SQL of the tool against one open session.

    The service rows are imported on construction: the module stays
    importable outside the homework container (unit tests run without
    SQLAlchemy and drive the wipe with fakes).
    """

    def __init__(self, session) -> None:
        from homework_service.infrastructure.models.homework import HomeworkRow
        from homework_service.infrastructure.models.homework_answer import (
            HomeworkAnswerRow,
        )
        from homework_service.infrastructure.models.homework_answer_file import (
            HomeworkAnswerFileRow,
        )
        from homework_service.infrastructure.models.homework_file import (
            HomeworkFileRow,
        )

        self._session = session
        self._homework_row = HomeworkRow
        self._answer_row = HomeworkAnswerRow
        self._answer_file_row = HomeworkAnswerFileRow
        self._file_row = HomeworkFileRow

    async def demo_homework_ids(self, teacher_ids, class_ids) -> list[int]:
        """Ids of the demo assignments: demo teacher x demo class."""
        from sqlalchemy import select

        if not teacher_ids or not class_ids:
            return []
        statement = select(self._homework_row.id).where(
            self._homework_row.author_id.in_(teacher_ids),
            self._homework_row.class_id.in_(class_ids),
        )
        return list((await self._session.scalars(statement)).all())

    async def _delete_by_homework(self, row_class, column, homework_ids) -> int:
        from sqlalchemy import delete

        if not homework_ids:
            return 0
        removed = 0
        for batch in in_batches(homework_ids):
            statement = delete(row_class).where(column.in_(batch))
            removed += (await self._session.execute(statement)).rowcount or 0
        return removed

    async def delete_answer_files(self, homework_ids) -> int:
        """Deletes the file links of the answers of the demo homework."""
        from sqlalchemy import delete, select

        if not homework_ids:
            return 0
        answer_ids = select(self._answer_row.id).where(
            self._answer_row.homework_id.in_(homework_ids)
        )
        statement = delete(self._answer_file_row).where(
            self._answer_file_row.answer_id.in_(answer_ids)
        )
        return (await self._session.execute(statement)).rowcount or 0

    async def delete_answers(self, homework_ids) -> int:
        """Deletes the answers of the demo homework."""
        return await self._delete_by_homework(
            self._answer_row, self._answer_row.homework_id, homework_ids
        )

    async def delete_files(self, homework_ids) -> int:
        """Deletes the attachment links of the demo homework."""
        return await self._delete_by_homework(
            self._file_row, self._file_row.homework_id, homework_ids
        )

    async def delete_assignments(self, homework_ids) -> int:
        """Deletes the demo assignment rows themselves."""
        return await self._delete_by_homework(
            self._homework_row, self._homework_row.id, homework_ids
        )


async def main():
    from homework_service.config import HomeworkSettings
    from homework_service.infrastructure.database import (
        create_engine,
        create_session_factory,
    )

    data = json.load(sys.stdin)
    if data.get("mode") != "wipe":
        raise SystemExit(f"Unsupported mode: {data.get('mode')!r}")
    engine = create_engine(HomeworkSettings().database_url)
    sessions = create_session_factory(engine)
    try:
        result = await run_wipe(
            SqlScenarioStore,
            sessions,
            parse_teachers(data["teacher_ids"]),
            parse_classes(data["class_ids"]),
        )
        print(json.dumps(result))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
