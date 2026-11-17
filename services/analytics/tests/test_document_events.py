"""Готовность документа не раскрывает ФИО в общем журнале."""

import json
from uuid import uuid4

import pytest

from analytics_service.application.audit import parse_audit_event


def test_document_event_contains_only_creator_and_job_references():
    event = {
        "event_id": str(uuid4()),
        "event_source": "documents",
        "event_type": "documents.document.completed",
        "schema_version": 1,
        "occurred_at": "2026-10-22T12:00:00Z",
        "request_id": None,
        "actor": {"source": "system", "id": "documents"},
        "payload": {
            "creator_id": str(uuid4()),
            "job_id": str(uuid4()),
            "document_type": "contract",
        },
    }
    assert (
        parse_audit_event(json.dumps(event).encode()).payload["document_type"]
        == "contract"
    )
    with pytest.raises(ValueError):
        parse_audit_event(
            json.dumps(
                event
                | {
                    "payload": event["payload"]
                    | {"student_full_name": "Лишние персональные данные"}
                }
            ).encode()
        )
