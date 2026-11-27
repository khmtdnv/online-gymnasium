"""Настройки сервиса из переменных окружения и файла .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class RelaySettings(BaseSettings):
    """Подключения к PostgreSQL и Kafka для публикации outbox."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    kafka_bootstrap_servers: str
    schedule_snapshot_topic: str = "schedule.lessons.v2"
    batch_size: int = 500
    published_retention_days: int = 7
    retention_interval_seconds: float = 3600.0


class InvalidatorSettings(BaseSettings):
    """Подключения к Kafka и Redis для удаления кеша расписания."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str
    redis_url: str
