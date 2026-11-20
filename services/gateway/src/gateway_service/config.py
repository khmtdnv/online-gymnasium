"""Настройки сервиса из переменных окружения и файла .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Настройки Gateway: база данных, секреты и сроки действия токенов."""

    app_name: str = "Gateway-service"

    database_url: str
    jwt_secret: str
    backoffice_service_token: str
    journal_service_token: str | None = None
    journal_base_url: str | None = None
    journal_read_service_token: str | None = None
    homework_base_url: str | None = None
    homework_service_token: str | None = None
    schedule_base_url: str | None = None
    schedule_service_token: str | None = None
    analytics_base_url: str | None = None
    analytics_read_service_token: str | None = None
    pen_base_url: str | None = None
    pen_service_token: str | None = None
    billing_base_url: str | None = None
    billing_service_token: str | None = None
    enforce_tuition_access: bool = False
    documents_base_url: str | None = None
    documents_service_token: str | None = None
    notifications_base_url: str | None = None
    notifications_service_token: str | None = None
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 60 * 60
    refresh_cookie_secure: bool = False
    public_origin: str = "http://localhost:8080"
    login_throttle_max_failures: int = 10
    login_throttle_window_seconds: int = 15 * 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
