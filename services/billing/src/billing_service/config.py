"""Настройки собственного процесса; реальные ключи в чат не передаются."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BillingSettings(BaseSettings):
    """Пустые ключи означают отключённую оплату, а не локальную подделку ЮKassa."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    gateway_service_token: str = Field(min_length=1)
    yookassa_shop_id: str = ""
    yookassa_secret_key: SecretStr = SecretStr("")
    public_origin: str = "http://localhost:8080"
    tuition_price_kopecks: int = Field(default=300000, ge=100, le=100000000)
    quarter_price_kopecks: int = Field(default=900000, ge=100, le=100000000)
