"""Настройки собственного процесса и отдельной БД Pen."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PenSettings(BaseSettings):
    """Служебный секрет не является пользовательским JWT."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    gateway_service_token: str = Field(min_length=1)
