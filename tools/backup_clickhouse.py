"""Создаёт штатный архив аналитической базы ClickHouse."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def create_backup(name: str) -> None:
    """Создаёт отдельный архив базы default внутри volume ClickHouse.

    Args:
        name: Уникальное имя из латинских букв, цифр, дефиса и подчёркивания.

    Raises:
        ValueError: Имя содержит недопустимые символы.
        subprocess.CalledProcessError: Команда ClickHouse завершилась ошибкой.
        RuntimeError: ClickHouse не подтвердил создание архива.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("Имя архива должно содержать только буквы, цифры, - и _")
    query = f"BACKUP DATABASE default TO File('backups/{name}.zip')"
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "analytics-clickhouse",
            "clickhouse-client",
            "--query",
            query,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    if (
        len(result.stdout.strip().split("\t")) != 2
        or result.stdout.strip().split("\t")[-1] != "BACKUP_CREATED"
    ):
        raise RuntimeError("ClickHouse не подтвердил создание архива")


def main() -> None:
    """Создаёт ручной архив, который необходимо отдельно выгрузить с VPS."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="Уникальное имя архива")
    args = parser.parse_args()
    create_backup(args.name)
    print("Архив ClickHouse создан внутри Docker volume; внешней копии пока нет.")


if __name__ == "__main__":
    main()
