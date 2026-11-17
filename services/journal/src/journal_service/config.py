"""Настройки Journal из окружения процесса и файла .env."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class JournalSettings(BaseSettings):
    """Хранит БД, служебные credentials и необязательную интеграцию Gateway."""

    database_url: str
    backoffice_service_token: str = Field(min_length=1)
    homework_service_token: str | None = Field(default=None, min_length=1)
    gateway_read_service_token: str | None = Field(default=None, min_length=1)
    billing_read_service_token: str | None = Field(default=None, min_length=1)
    app_name: str = "Journal-service"
    gateway_base_url: str | None = None
    gateway_service_token: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
