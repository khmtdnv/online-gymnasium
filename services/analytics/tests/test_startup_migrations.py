"""Проверяет подготовку обеих схем перед запуском Analytics."""

from analytics_service.workers import migrate_audit


def test_startup_prepares_workload_and_audit_schema(monkeypatch):
    """Снимки уроков должны быть доступны до запуска потребителя Kafka."""
    events = []

    class Client:
        def close(self):
            events.append("close")

    client = Client()
    monkeypatch.setattr(migrate_audit, "AnalyticsApiSettings", lambda: object())
    monkeypatch.setattr(migrate_audit, "create_client", lambda settings: client)
    monkeypatch.setattr(
        migrate_audit,
        "prepare_uuid_schema",
        lambda value: events.append("workload"),
        raising=False,
    )
    monkeypatch.setattr(
        migrate_audit, "prepare_audit_schema", lambda value: events.append("audit")
    )
    migrate_audit.main()
    assert events == ["workload", "audit", "close"]
