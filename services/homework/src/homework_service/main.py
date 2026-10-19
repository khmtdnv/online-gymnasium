"""Точка запуска: uvicorn homework_service.main:app."""

from homework_service.app import create_app
from homework_service.config import HomeworkSettings
from homework_service.infrastructure.database import create_engine

settings = HomeworkSettings()
app = create_app(settings, create_engine(settings.database_url))
