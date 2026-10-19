"""Настройки без неявного рабочего подключения."""

import pytest
from pydantic import ValidationError


def test_database_url_is_required(monkeypatch):
    from homework_service.config import HomeworkSettings

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        HomeworkSettings(_env_file=None)


def test_optional_owner_configuration_and_environment_priority(monkeypatch, tmp_path):
    from homework_service.config import HomeworkSettings

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://env/homework")
    settings = HomeworkSettings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://env/homework"
    assert settings.schedule_service_token is None
    assert settings.journal_service_token is None
