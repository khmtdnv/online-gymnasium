"""Аудит отклоняет лишние персональные данные и не смешивает источники ID."""

import json
from uuid import UUID

import pytest


def review_event():
    return {
        "event_id": str(UUID(int=1)),
        "event_source": "homework",
        "event_type": "homework.answer.reviewed",
        "schema_version": 1,
        "occurred_at": "2026-10-22T10:00:00Z",
        "request_id": None,
        "actor": {"source": "gateway", "id": str(UUID(int=2))},
        "payload": {
            "answer_id": 10,
            "homework_id": 1,
            "student_id": str(UUID(int=3)),
            "class_id": 7,
            "subject_id": 3,
            "teacher_id": str(UUID(int=2)),
            "status": "graded",
            "grade": 4,
        },
    }


def test_backoffice_payment_action_accepts_only_identifiers():
    """Аудит сохраняет ID платежа и подтверждённого администратора без секретов."""
    from analytics_service.application.audit import parse_audit_event

    event = {
        "event_id": str(UUID(int=1)),
        "event_source": "backoffice",
        "event_type": "backoffice.action.recorded",
        "schema_version": 1,
        "occurred_at": "2026-10-22T10:00:00Z",
        "request_id": None,
        "actor": {"source": "backoffice", "id": "7"},
        "payload": {
            "record_id": 1,
            "action": "refund_payment",
            "succeeded": True,
            "result_code": "request_accepted",
            "target_ids": {"payment_id": 123, "user_id": str(UUID(int=2))},
        },
    }
    parsed = parse_audit_event(json.dumps(event).encode())
    assert parsed.payload["target_ids"]["payment_id"] == 123
    event["payload"]["target_ids"]["password"] = "secret"
    with pytest.raises(ValueError):
        parse_audit_event(json.dumps(event).encode())


def test_parser_checks_source_version_and_private_fields():
    from analytics_service.application.audit import parse_audit_event

    result = parse_audit_event(json.dumps(review_event()).encode())
    assert result.event_id == UUID(int=1)
    assert result.payload["grade"] == 4
    for change in (
        {"schema_version": True},
        {"schema_version": 2},
        {"event_source": "journal"},
        {"occurred_at": "9999-01-01T00:00:00Z"},
        {"payload": {**review_event()["payload"], "answer_text": "private"}},
        {"payload": {**review_event()["payload"], "status": "returned"}},
        {"actor": {"source": "backoffice", "id": "2"}},
    ):
        with pytest.raises(ValueError):
            parse_audit_event(json.dumps(review_event() | change).encode())


def test_schedule_adapter_keeps_stable_identity_without_inventing_an_actor():
    from analytics_service.application.audit import parse_schedule_audit_event

    value = json.dumps(
        {
            "event_id": 42,
            "event_type": "lesson.snapshot",
            "schema_version": 2,
            "occurred_at": "2026-10-22T10:00:00Z",
            "payload": {
                "lesson_id": 1,
                "class_id": 7,
                "teacher_id": str(UUID(int=2)),
                "subject_id": 3,
                "starts_at": "2026-10-22T11:00:00Z",
                "ends_at": "2026-10-22T12:00:00Z",
                "status": "planned",
                "version": 1,
            },
        }
    ).encode()
    first = parse_schedule_audit_event(value)
    assert first == parse_schedule_audit_event(value)
    assert first.actor.source == "system" and first.actor.id == "schedule"
    assert first.event_type == "schedule.lesson.changed"


def test_schedule_references_fit_the_source_database_before_storage():
    from analytics_service.application.audit import parse_audit_event

    event = review_event() | {
        "event_source": "schedule",
        "event_type": "schedule.lesson.changed",
        "actor": {"source": "system", "id": "schedule"},
        "payload": {
            "lesson_id": 1,
            "class_id": 7,
            "teacher_id": str(UUID(int=2)),
            "subject_id": 3,
            "starts_at": "2026-10-22T11:00:00Z",
            "ends_at": "2026-10-22T12:00:00Z",
            "status": "planned",
            "version": 1,
        },
    }
    for field in ("lesson_id", "class_id", "subject_id"):
        with pytest.raises(ValueError):
            parse_audit_event(
                json.dumps(
                    event | {"payload": event["payload"] | {field: 2**40}}
                ).encode()
            )


def test_login_registration_and_admin_actions_keep_actor_namespaces():
    from analytics_service.application.audit import parse_audit_event

    envelope = review_event()
    envelope.update(
        event_source="gateway",
        event_type="gateway.user.logged_in",
        payload={"user_id": str(UUID(int=2)), "role": "student"},
    )
    assert parse_audit_event(json.dumps(envelope).encode()).actor.source == "gateway"
    with pytest.raises(ValueError):
        parse_audit_event(
            json.dumps(
                envelope | {"payload": envelope["payload"] | {"password": "private"}}
            ).encode()
        )
    envelope.update(
        event_type="gateway.user.created",
        actor={"source": "service", "id": "backoffice"},
    )
    assert parse_audit_event(json.dumps(envelope).encode()).actor.id == "backoffice"
    envelope.update(
        event_source="backoffice",
        event_type="backoffice.action.recorded",
        actor={"source": "backoffice", "id": "1"},
        payload={
            "record_id": 1,
            "action": "create_user",
            "succeeded": False,
            "result_code": "request_error",
            "target_ids": {},
        },
    )
    assert (
        parse_audit_event(json.dumps(envelope).encode()).payload["succeeded"] is False
    )
    with pytest.raises(ValueError):
        parse_audit_event(
            json.dumps(
                envelope
                | {
                    "payload": envelope["payload"]
                    | {"target_ids": {"password": "private"}}
                }
            ).encode()
        )
