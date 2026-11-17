"""Настройки отдельного процесса; транспорт Kafka добавляет worker-env."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NotificationSettings(BaseSettings):
    """Собственная БД и отдельная служебная пара Gateway."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    gateway_service_token: str = Field(min_length=1)
