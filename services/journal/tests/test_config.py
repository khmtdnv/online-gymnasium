"""Проверки чтения и обязательности настроек Journal."""

import pytest
from pydantic import ValidationError


def test_gateway_settings_are_optional(monkeypatch) -> None:
    """Не требует Gateway для существующих чтений Journal."""
    from journal_service.config import JournalSettings

    monkeypatch.delenv("GATEWAY_BASE_URL", raising=False)
    monkeypatch.delenv("GATEWAY_SERVICE_TOKEN", raising=False)
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="journal-backoffice-test",
        _env_file=None,
    )
    assert settings.gateway_base_url is None
    assert settings.gateway_service_token is None


def test_gateway_settings_read_separate_credentials(monkeypatch) -> None:
    """Не подменяет исходящий секрет входящим токеном Backoffice."""
    from journal_service.config import JournalSettings

    monkeypatch.setenv("GATEWAY_BASE_URL", "http://gateway-api:8000")
    monkeypatch.setenv("GATEWAY_SERVICE_TOKEN", "journal-to-gateway-test")
    settings = JournalSettings(
        database_url="postgresql+asyncpg://journal:test@localhost/journal",
        backoffice_service_token="backoffice-to-journal-test",
        _env_file=None,
    )
    assert settings.gateway_base_url == "http://gateway-api:8000"
    assert settings.gateway_service_token == "journal-to-gateway-test"


def test_settings_rejects_empty_service_token() -> None:
    """Не позволяет запустить сервис с пустым служебным секретом."""
    from journal_service.config import JournalSettings

    with pytest.raises(ValidationError) as exc_info:
        JournalSettings(
            database_url="postgresql+asyncpg://journal:test@localhost/journal",
            backoffice_service_token="",
            _env_file=None,
        )

    assert any(
        error["loc"] == ("backoffice_service_token",)
        for error in exc_info.value.errors()
    )


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Читает адрес БД и служебный токен из окружения процесса."""
    from journal_service.config import JournalSettings

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://journal:test-password@localhost:5436/journal",
    )
    monkeypatch.setenv("BACKOFFICE_SERVICE_TOKEN", "test-journal-service-token")
    monkeypatch.delenv("APP_NAME", raising=False)

    settings = JournalSettings(_env_file=None)

    assert settings.database_url == (
        "postgresql+asyncpg://journal:test-password@localhost:5436/journal"
    )
    assert settings.backoffice_service_token == "test-journal-service-token"
    assert settings.app_name == "Journal-service"


@pytest.mark.parametrize(
    ("missing_environment_variable", "missing_field"),
    [
        ("DATABASE_URL", "database_url"),
        ("BACKOFFICE_SERVICE_TOKEN", "backoffice_service_token"),
    ],
)
def test_settings_requires_database_and_service_token(
    monkeypatch: pytest.MonkeyPatch,
    missing_environment_variable: str,
    missing_field: str,
) -> None:
    """Не позволяет создать настройки без обязательного значения."""
    from journal_service.config import JournalSettings

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://journal:test-password@localhost:5436/journal",
    )
    monkeypatch.setenv("BACKOFFICE_SERVICE_TOKEN", "test-journal-service-token")
    monkeypatch.delenv(missing_environment_variable)

    with pytest.raises(ValidationError) as exc_info:
        JournalSettings(_env_file=None)

    assert any(
        error["loc"] == (missing_field,) and error["type"] == "missing"
        for error in exc_info.value.errors()
    )
