"""Создаёт согласованные локальные env-файлы для нового checkout.

Существующие файлы никогда не заменяются. Не использовать с существующими
томами PostgreSQL: новые пароли не меняют уже инициализированные базы.
"""

import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def initialize(root: Path) -> int:
    """Создаёт файлы из примеров, согласуя парные секреты без вывода значений."""
    examples = sorted((root / "services").glob("*/.*.env.example"))
    examples += sorted((root / "services").glob("*/.env.example"))
    targets = [
        example.with_name(example.name.removesuffix(".example")) for example in examples
    ]
    if not examples:
        raise ValueError("Примеры env-файлов не найдены")
    if any(target.exists() or target.is_symlink() for target in targets):
        raise FileExistsError(
            "Обнаружены существующие env-файлы; настройки не изменены"
        )

    data = {}
    for example, target in zip(examples, targets, strict=True):
        lines = example.read_text().splitlines()
        data[str(target.relative_to(root))] = lines

    def set_value(path: str, key: str, value: str) -> None:
        lines = data[path]
        matches = [i for i, line in enumerate(lines) if line.startswith(key + "=")]
        if len(matches) != 1:
            raise ValueError(f"Не найдено единственное поле {key} в {path}")
        lines[matches[0]] = f"{key}={value}"

    def pair(*items: tuple[str, str]) -> None:
        value = secrets.token_hex(20)
        for path, key in items:
            set_value(f"services/{path}", key, value)

    pairs = [
        (
            ("gateway/.env", "BACKOFFICE_SERVICE_TOKEN"),
            ("backoffice/.env", "BACKOFFICE_GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("journal/.env", "BACKOFFICE_SERVICE_TOKEN"),
            ("backoffice/.env", "BACKOFFICE_JOURNAL_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "JOURNAL_SERVICE_TOKEN"),
            ("journal/.env", "GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "JOURNAL_READ_SERVICE_TOKEN"),
            ("journal/.env", "GATEWAY_READ_SERVICE_TOKEN"),
        ),
        (
            ("billing/.worker.env", "JOURNAL_SERVICE_TOKEN"),
            ("journal/.env", "BILLING_READ_SERVICE_TOKEN"),
        ),
        (
            ("homework/.env", "JOURNAL_SERVICE_TOKEN"),
            ("journal/.env", "HOMEWORK_SERVICE_TOKEN"),
        ),
        (
            ("homework/.env", "SCHEDULE_SERVICE_TOKEN"),
            ("schedule/.env", "HOMEWORK_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "HOMEWORK_SERVICE_TOKEN"),
            ("homework/.env", "GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "SCHEDULE_SERVICE_TOKEN"),
            ("schedule/.env", "GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "ANALYTICS_READ_SERVICE_TOKEN"),
            ("analytics/.env", "GATEWAY_READ_SERVICE_TOKEN"),
        ),
        (("gateway/.env", "PEN_SERVICE_TOKEN"), ("pen/.env", "GATEWAY_SERVICE_TOKEN")),
        (
            ("gateway/.env", "BILLING_SERVICE_TOKEN"),
            ("billing/.env", "GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "DOCUMENTS_SERVICE_TOKEN"),
            ("documents/.env", "GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("gateway/.env", "NOTIFICATIONS_SERVICE_TOKEN"),
            ("notifications/.env", "GATEWAY_SERVICE_TOKEN"),
        ),
        (
            ("homework/.env", "MINIO_SECRET_KEY"),
            ("homework/.minio.env", "MINIO_SECRET_KEY"),
        ),
        (
            ("documents/.env", "MINIO_SECRET_KEY"),
            ("documents/.minio.env", "MINIO_ROOT_PASSWORD"),
        ),
    ]
    for group in pairs:
        pair(*group)
    for path, key in (
        ("gateway/.env", "JWT_SECRET"),
        ("backoffice/.env", "BACKOFFICE_SECRET_KEY"),
        ("homework/.minio.env", "MINIO_ROOT_PASSWORD"),
        ("analytics/.clickhouse.env", "CLICKHOUSE_PASSWORD"),
    ):
        pair((path, key))

    for service in (
        "gateway",
        "journal",
        "homework",
        "schedule",
        "billing",
        "pen",
        "notifications",
        "documents",
    ):
        password = secrets.token_hex(24)
        set_value(f"services/{service}/.postgres.env", "POSTGRES_PASSWORD", password)
        path = f"services/{service}/.env"
        key = "DOCUMENT_DATABASE_URL" if service == "documents" else "DATABASE_URL"
        line = next(line for line in data[path] if line.startswith(key + "="))
        parsed = urlsplit(line.split("=", 1)[1])
        url = urlunsplit(
            (
                parsed.scheme,
                f"{parsed.username}:{password}@{parsed.hostname}:{parsed.port}",
                parsed.path,
                parsed.query,
                parsed.fragment,
            )
        )
        set_value(path, key, url)
    password = secrets.token_hex(24)
    set_value("services/backoffice/.postgres.env", "POSTGRES_PASSWORD", password)
    set_value("services/backoffice/.env", "BACKOFFICE_DB_PASSWORD", password)
    password = secrets.token_hex(24)
    set_value("services/documents/.rabbitmq.env", "RABBITMQ_DEFAULT_PASS", password)
    set_value(
        "services/documents/.env",
        "CELERY_BROKER_URL",
        f"amqp://documents:{password}@document-rabbitmq:5672//",
    )
    # Schedule хранит URL для совместимости, хотя сейчас его не использует.
    set_value(
        "services/schedule/.env",
        "RABBITMQ_URL",
        f"amqp://documents:{password}@document-rabbitmq:5672//",
    )

    for path, lines in data.items():
        fd = os.open(root / path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines) + "\n")
    return len(targets)


if __name__ == "__main__":
    try:
        count = initialize(Path(__file__).resolve().parents[1])
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Создано env-файлов: {count}. Секреты в терминал не выводятся.")
