"""Настройки relay из собственных env-файлов процесса."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RelaySettings(BaseSettings):
    """Подключения БД и Kafka; API не должен знать параметры брокера."""

    model_config = SettingsConfigDict(env_file=(".env", ".worker.env"), extra="ignore")
    database_url: str
    kafka_bootstrap_servers: str
    platform_events_topic: str = "platform.events.v1"
    batch_size: int = Field(default=100, ge=1, le=1000)
