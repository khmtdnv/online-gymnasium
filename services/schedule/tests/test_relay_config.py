from pytest import MonkeyPatch


def test_relay_settings_reads_database_and_kafka_urls_from_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    from schedule_service.workers.config import RelaySettings

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://schedule:password@postgres:5432/schedule"
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")

    settings = RelaySettings()

    assert (
        settings.database_url
        == "postgresql+asyncpg://schedule:password@postgres:5432/schedule"
    )
    assert settings.kafka_bootstrap_servers == "kafka:19092"


def test_relay_settings_reads_batch_size_and_retention_from_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    from schedule_service.workers.config import RelaySettings

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://schedule:password@postgres:5432/schedule"
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
    monkeypatch.setenv("BATCH_SIZE", "750")
    monkeypatch.setenv("PUBLISHED_RETENTION_DAYS", "14")
    monkeypatch.setenv("RETENTION_INTERVAL_SECONDS", "7200")

    settings = RelaySettings()

    assert settings.batch_size == 750
    assert settings.published_retention_days == 14
    assert settings.retention_interval_seconds == 7200.0


def test_relay_settings_defaults_match_the_year_pipeline_spec(
    monkeypatch: MonkeyPatch,
) -> None:
    from schedule_service.workers.config import RelaySettings

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://schedule:password@postgres:5432/schedule"
    )
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")

    settings = RelaySettings()

    assert settings.batch_size == 500
    assert settings.published_retention_days == 7
    assert settings.retention_interval_seconds == 3600.0
