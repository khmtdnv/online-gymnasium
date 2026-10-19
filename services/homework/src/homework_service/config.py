"""Настройки процесса из окружения и локального .env."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HomeworkSettings(BaseSettings):
    """Хранит URL своей БД и отдельные credentials владельцев данных."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(min_length=1)
    app_name: str = "OG1 Homework Service"
    gateway_service_token: str | None = Field(default=None, min_length=1)
    schedule_base_url: str | None = None
    schedule_service_token: str | None = Field(default=None, min_length=1)
    journal_base_url: str | None = None
    journal_service_token: str | None = Field(default=None, min_length=1)
