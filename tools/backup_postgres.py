"""Создаёт архивы PostgreSQL для локального демо."""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES = (
    "backoffice-postgres",
    "billing-postgres",
    "document-postgres",
    "gateway-postgres",
    "homework-postgres",
    "journal-postgres",
    "notifications-postgres",
    "pen-postgres",
    "schedule-postgres",
)
PG_DUMP = (
    'export PGPASSWORD="$POSTGRES_PASSWORD"; '
    'exec pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" '
    '-d "$POSTGRES_DB" --format=custom --no-owner --no-privileges'
)


def create_backup(target: Path) -> None:
    """Сохраняет отдельные дампы только в новой закрытой папке.

    Args:
        target: Ещё не существующая папка в существующем каталоге.

    Raises:
        FileExistsError: Папка уже существует и не будет перезаписана.
        subprocess.CalledProcessError: Один из дампов не удалось создать.
        ValueError: Результат не похож на архив PostgreSQL.
    """
    target.mkdir(mode=0o700)
    for service in SERVICES:
        destination = target / f"{service}.dump"
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as archive:
            subprocess.run(
                ["docker", "compose", "exec", "-T", service, "sh", "-c", PG_DUMP],
                stdout=archive,
                check=True,
                cwd=ROOT,
            )
        with destination.open("rb") as archive:
            if archive.read(5) != b"PGDMP":
                raise ValueError(f"Некорректный архив: {service}")
    marker = os.open(target / "COMPLETE", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(marker)


def main() -> None:
    """Запускает ручное создание дампов без автоматического удаления."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Новая папка для дампов")
    args = parser.parse_args()
    create_backup(args.directory)
    print("Дампы PostgreSQL созданы. Файлы и ClickHouse в них не входят.")


if __name__ == "__main__":
    main()
