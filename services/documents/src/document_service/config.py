"""Настройки сервиса из переменных окружения и файла .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DocumentSettings(BaseSettings):
    """Подключения сервиса документов к PostgreSQL, RabbitMQ и MinIO."""

    document_database_url: str
    celery_broker_url: str
    minio_endpoint: str
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "documents"
    minio_secure: bool = False
    gateway_service_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
