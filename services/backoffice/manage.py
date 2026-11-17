#!/usr/bin/env python
"""Точка запуска команд Django для сервиса Backoffice."""

import os
import sys


def main():
    """Запускает команду управления Django с настройками Backoffice."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backoffice.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
