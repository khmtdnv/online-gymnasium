"""Финансовые события содержат только ссылки/сумму, не карту и не providersecret."""

import json
from uuid import uuid4

import pytest


def test_billing_contract_keeps_system_actor_and_rejects_private_fields():
    from analytics_service.application.audit import parse_audit_event

    envelope = {
        "event_id": str(uuid4()),
        "event_source": "billing",
        "event_type": "billing.payment.succeeded",
        "schema_version": 1,
        "occurred_at": "2026-10-22T12:00:00Z",
        "request_id": None,
        "actor": {"source": "system", "id": "billing"},
        "payload": {
            "payment_id": 1,
            "order_id": 2,
            "student_id": str(uuid4()),
            "payer_id": str(uuid4()),
            "study_month": "2026-10-01",
            "amount_kopecks": 300000,
            "currency": "RUB",
            "refund_actor_id": None,
        },
    }
    assert (
        parse_audit_event(json.dumps(envelope).encode()).payload["amount_kopecks"]
        == 300000
    )
    quarter = envelope | {"payload": envelope["payload"] | {"period_type": "quarter"}}
    assert (
        parse_audit_event(json.dumps(quarter).encode()).payload["period_type"]
        == "quarter"
    )
    for change in (
        {"payload": envelope["payload"] | {"secret_key": "private"}},
        {"actor": {"source": "system", "id": "schedule"}},
        {"payload": envelope["payload"] | {"study_month": "2026-10-02"}},
    ):
        with pytest.raises(ValueError):
            parse_audit_event(json.dumps(envelope | change).encode())
