"""Настройки процесса из окружения и локального .env."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class HomeworkSettings(BaseSettings):
    """Хранит URL своей БД и отдельные credentials владельцев данных."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(min_length=1)
    app_name: str = "OG Homework Service"
    gateway_service_token: str | None = Field(default=None, min_length=1)
    schedule_base_url: str | None = None
    schedule_service_token: str | None = Field(default=None, min_length=1)
    journal_base_url: str | None = None
    journal_service_token: str | None = Field(default=None, min_length=1)
    minio_endpoint: str | None = Field(default=None, min_length=1)
    minio_access_key: str | None = Field(default=None, min_length=1)
    minio_secret_key: SecretStr | None = None
    minio_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    minio_secure: bool = False
