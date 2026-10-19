"""Изолированные настройки Django: тесты не используют рабочую БД и секреты."""

from pathlib import Path

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="backoffice-test-only-key",
        ALLOWED_HOSTS=["testserver"],
        ROOT_URLCONF="backoffice.urls",
        INSTALLED_APPS=[
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "backoffice_admin",
        ],
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [
                    Path(__file__).resolve().parents[1]
                    / "src/backoffice_admin/templates"
                ],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ]
                },
            }
        ],
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        LANGUAGE_CODE="ru-ru",
        STATIC_URL="/static/",
        USE_TZ=True,
        GATEWAY_BASE_URL="http://gateway.test",
        GATEWAY_SERVICE_TOKEN="test-service-token",
    )
    django.setup()
