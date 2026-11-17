"""Настройки Django Backoffice из переменных окружения процесса."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ["BACKOFFICE_SECRET_KEY"]

DEBUG = os.getenv("BACKOFFICE_DEBUG", "False") == "True"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("BACKOFFICE_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "backoffice_admin.apps.BackofficeAdminConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "backoffice_admin.sso_middleware.GatewaySessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backoffice.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "src/backoffice_admin/templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backoffice.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["BACKOFFICE_DB_NAME"],
        "USER": os.environ["BACKOFFICE_DB_USER"],
        "PASSWORD": os.environ["BACKOFFICE_DB_PASSWORD"],
        "HOST": os.environ["BACKOFFICE_DB_HOST"],
        "PORT": os.environ["BACKOFFICE_DB_PORT"],
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "ru-ru"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# В локальном single-origin запуске Django сам проверяет Host/Origin запроса.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("BACKOFFICE_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
SESSION_COOKIE_SECURE = os.getenv("BACKOFFICE_SECURE_COOKIES", "False") == "True"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
# Включать лишь за proxy, который заменяет, а не пропускает этот заголовок.
if os.getenv("BACKOFFICE_TRUST_PROXY", "False") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}


GATEWAY_BASE_URL = os.environ["BACKOFFICE_GATEWAY_BASE_URL"]
GATEWAY_SERVICE_TOKEN = os.environ["BACKOFFICE_GATEWAY_SERVICE_TOKEN"]

# Новая форма недоступна без настроек, остальные страницы продолжают работать.
JOURNAL_BASE_URL = os.getenv("BACKOFFICE_JOURNAL_BASE_URL", "")
JOURNAL_SERVICE_TOKEN = os.getenv("BACKOFFICE_JOURNAL_SERVICE_TOKEN", "")
