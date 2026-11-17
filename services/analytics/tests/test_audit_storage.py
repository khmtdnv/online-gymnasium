"""Повтор события не удваивает оценки даже до слияния частей ClickHouse."""

import asyncio
import json
from datetime import date
from uuid import UUID

from test_audit_events import review_event

from analytics_service.application.audit import (
    AuditQuery,
    ProgressQuery,
    parse_audit_event,
)
from analytics_service.infrastructure.clickhouse_audit_repository import (
    ClickHouseAuditRepository,
)


def test_duplicate_reviews_count_once_without_merge_and_return_is_not_a_grade(
    legacy_clickhouse,
):
    from analytics_service.workers.migrate_audit import prepare_audit_schema

    prepare_audit_schema(legacy_clickhouse)
    repository = ClickHouseAuditRepository(legacy_clickhouse)

    async def run():
        graded = parse_audit_event(json.dumps(review_event()).encode())
        returned = review_event()
        returned["event_id"] = str(UUID(int=2))
        returned["payload"] |= {"answer_id": 11, "status": "returned", "grade": None}
        await repository.add_many(
            [graded, graded, parse_audit_event(json.dumps(returned).encode())]
        )
        rows = await repository.get_progress(
            ProgressQuery(
                class_id=7,
                date_from=date(2026, 10, 22),
                date_to=date(2026, 10, 22),
            )
        )
        assert len(rows) == 1
        assert rows[0].graded_count == 1 and rows[0].average_grade == 4
        page = await repository.list_events(
            AuditQuery(
                date_from=date(2026, 10, 22),
                date_to=date(2026, 10, 22),
            )
        )
        assert len(page) == 2
        assert (
            await repository.get_progress(
                ProgressQuery(
                    class_id=8,
                    date_from=date(2026, 10, 22),
                    date_to=date(2026, 10, 22),
                )
            )
            == []
        )
        assert (
            await repository.get_progress(
                ProgressQuery(
                    class_id=7,
                    date_from=date(2026, 10, 23),
                    date_to=date(2026, 10, 23),
                )
            )
            == []
        )

    asyncio.run(run())
