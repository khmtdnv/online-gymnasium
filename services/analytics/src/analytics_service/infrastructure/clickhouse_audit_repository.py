"""Запись аудита и дедуплицированные чтения до фонового слияния ClickHouse."""

import asyncio
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from analytics_service.application.audit import (
    AuditEvent,
    AuditQuery,
    ProgressQuery,
    ProgressRow,
)

COLUMNS = [
    "event_id",
    "occurred_at",
    "event_source",
    "event_type",
    "actor_source",
    "actor_id",
    "envelope_json",
    "student_id",
    "class_id",
    "subject_id",
    "answer_id",
    "review_status",
    "grade",
]


class ClickHouseAuditRepository:
    """Не полагается на момент background merge для корректности отчёта."""

    def __init__(self, client) -> None:
        self._client = client

    async def add_many(self, events: list[AuditEvent]) -> None:
        """Записывает только проверенные конверты одним INSERT в отдельном потоке."""
        if not events:
            return
        rows = []
        for event in events:
            payload = event.payload
            current = payload.get("current") or payload.get("previous") or {}
            rows.append(
                [
                    event.event_id,
                    event.occurred_at.astimezone(UTC),
                    event.event_source,
                    event.event_type,
                    event.actor.source,
                    event.actor.id,
                    event.model_dump_json(),
                    UUID(payload["student_id"]) if payload.get("student_id") else None,
                    payload.get("class_id", current.get("class_id")),
                    payload.get("subject_id"),
                    payload.get("answer_id"),
                    payload.get("status") if event.event_source == "homework" else None,
                    payload.get("grade"),
                ]
            )
        await asyncio.to_thread(
            self._client.insert, "audit_events_v1", rows, column_names=COLUMNS
        )

    @staticmethod
    def parameters(query: AuditQuery) -> dict:
        """Отчёт использует UTC-дни событий; значения передаются SQL-параметрами."""
        return {
            "start": datetime.combine(query.date_from, time.min, UTC),
            "end": datetime.combine(query.date_to + timedelta(days=1), time.min, UTC),
            "source": getattr(query, "event_source", None) or "",
            "type": getattr(query, "event_type", None) or "",
            "limit": getattr(query, "limit", 50),
            "offset": getattr(query, "offset", 0),
        }

    async def list_events(self, query: AuditQuery) -> list[AuditEvent]:
        """Возвращает страницу без повторов по event_id и без раскрытия CH SQL."""
        result = await asyncio.to_thread(
            self._client.query,
            """
            SELECT envelope_json FROM audit_events_v1 FINAL
            WHERE occurred_at >= {start:DateTime64(6, 'UTC')}
              AND occurred_at < {end:DateTime64(6, 'UTC')}
              AND ({source:String} = '' OR event_source = {source:String})
              AND ({type:String} = '' OR event_type = {type:String})
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT {limit:UInt32} OFFSET {offset:UInt32}
        """,
            parameters=self.parameters(query),
        )
        return [AuditEvent.model_validate_json(row[0]) for row in result.result_rows]

    async def get_progress(self, query: ProgressQuery) -> list[ProgressRow]:
        """Считает проверенные попытки, не возвращённые работы и не дубли доставки."""
        parameters = self.parameters(query) | {"class_id": query.class_id}
        result = await asyncio.to_thread(
            self._client.query,
            """
            SELECT student_id, subject_id, count(), round(avg(last_grade), 2)
            FROM (
                SELECT student_id, subject_id, answer_id,
                       argMax(grade, tuple(occurred_at, event_id)) AS last_grade
                FROM audit_events_v1 FINAL
                WHERE event_type = 'homework.answer.reviewed'
                  AND class_id = {class_id:UInt32}
                  AND occurred_at >= {start:DateTime64(6, 'UTC')}
                  AND occurred_at < {end:DateTime64(6, 'UTC')}
                  AND review_status = 'graded'
                GROUP BY student_id, subject_id, answer_id
            )
            GROUP BY student_id, subject_id
            ORDER BY student_id, subject_id LIMIT 1001
        """,
            parameters=parameters,
        )
        if len(result.result_rows) > 1000:
            raise ValueError("Too many progress rows; narrow the period")
        return [
            ProgressRow(
                student_id=row[0],
                subject_id=row[1],
                graded_count=row[2],
                average_grade=float(row[3]),
            )
            for row in result.result_rows
        ]
