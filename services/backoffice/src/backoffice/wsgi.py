"""WSGI-точка запуска Django Backoffice, например через Gunicorn."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backoffice.settings")

application = get_wsgi_application()
