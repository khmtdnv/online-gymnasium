"""Настройки сервиса из переменных окружения и файла .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalyticsSettings(BaseSettings):
    """Подключения аналитического воркера и название очереди битых событий."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str

    clickhouse_user: str
    clickhouse_password: str
    clickhouse_host: str
    clickhouse_port: int

    analytics_dlq_topic: str
    schedule_snapshot_topic: str = "schedule.lessons.v2"
    schedule_snapshot_group_id: str = "schedule-analytics-v2"
    clickhouse_database: str = "default"


class AnalyticsApiSettings(BaseSettings):
    """Настройки ClickHouse для API дневной нагрузки."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    clickhouse_host: str
    clickhouse_port: int
    clickhouse_database: str = "default"
    clickhouse_user: str
    clickhouse_password: str
