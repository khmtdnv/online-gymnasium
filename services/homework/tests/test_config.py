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


def test_optional_file_storage_configuration_hides_secret():
    from homework_service.config import HomeworkSettings

    settings = HomeworkSettings(
        database_url="test",
        minio_endpoint="homework-minio:9000",
        minio_access_key="homework-files",
        minio_secret_key="private-password",
        minio_bucket="homework-files",
        _env_file=None,
    )
    assert settings.minio_endpoint == "homework-minio:9000"
    assert settings.minio_secret_key.get_secret_value() == "private-password"
    assert "private-password" not in repr(settings)


@pytest.mark.parametrize("partial", [False, True])
def test_unconfigured_storage_does_not_disable_json_creation(partial):
    from homework_service.config import HomeworkSettings
    from homework_service.infrastructure.minio_file_storage import create_file_storage

    settings = HomeworkSettings(
        database_url="test",
        _env_file=None,
        **({"minio_endpoint": "homework-minio:9000"} if partial else {}),
    )
    assert create_file_storage(settings) is None
