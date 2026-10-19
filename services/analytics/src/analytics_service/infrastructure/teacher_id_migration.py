"""Одноразовый offline-перенос истории в UUID-схему без удаления старых снимков."""

import json
import re
from collections import Counter
from datetime import UTC
from pathlib import Path
from uuid import UUID

from clickhouse_connect.driver import Client

from analytics_service.infrastructure.clickhouse_snapshot_repository import COLUMN_NAMES


class TeacherIdMigrationError(Exception):
    """История не может быть перенесена без полного однозначного соответствия."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TeacherIdMigrationError("Duplicate teacher ID mapping key")
        result[key] = value
    return result


def load_teacher_id_mapping(path: Path) -> dict[int, UUID]:
    """Читает подтверждённые соответствия, не генерируя UUID вместо неизвестных.

    Args:
        path: Одноразовый JSON-файл старый ID→UUID.

    Returns:
        Проверенные однозначные соответствия.

    Raises:
        TeacherIdMigrationError: Файл повреждён, недоступен или неоднозначен.
    """
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
        if not isinstance(raw, dict):
            raise TeacherIdMigrationError("Mapping must be a JSON object")
        result = {}
        for key, value in raw.items():
            if not re.fullmatch(r"[1-9][0-9]{0,9}", key) or not isinstance(value, str):
                raise ValueError("Invalid mapping entry")
            result[int(key)] = UUID(value)
    except (OSError, UnicodeError, ValueError) as exc:
        raise TeacherIdMigrationError("Cannot read teacher ID mapping") from exc
    _validate_mapping(result)
    return result


def _validate_mapping(mapping):
    if any(
        type(k) is not int or not 1 <= k <= 2147483647 or not isinstance(v, UUID)
        for k, v in mapping.items()
    ):
        raise TeacherIdMigrationError("Invalid teacher ID mapping")
    if len(set(mapping.values())) != len(mapping):
        raise TeacherIdMigrationError("Ambiguous teacher ID mapping")


def prepare_uuid_schema(client: Client) -> None:
    """Создаёт новые таблицы и отчёт, не меняя legacy-таблицы.

    Args:
        client: Соединение с выбранной БД ClickHouse.

    Raises:
        ClickHouseError: DDL не выполнен; старые данные остаются на месте.
    """
    directory = Path(__file__).resolve().parents[3] / "sql"
    for name in ("002_uuid_lesson_snapshots.sql", "003_uuid_class_daily_workload.sql"):
        for statement in (directory / name).read_text(encoding="utf-8").split(";"):
            if statement.strip():
                client.command(statement)


def legacy_teacher_ids(client: Client) -> set[int]:
    """Читает преподавателей всей сохранённой истории, а не только новых уроков.

    Args:
        client: Соединение с исходной БД ClickHouse.

    Returns:
        Старые числовые ID; пустое множество для новой БД без legacy-таблицы.
    """
    if not client.command("EXISTS TABLE lesson_snapshots"):
        return set()
    return {
        row[0]
        for row in client.query(
            "SELECT DISTINCT teacher_id FROM lesson_snapshots"
        ).result_rows
    }


def migrate_teacher_ids(
    client: Client, mapping: dict[int, UUID], *, check_only: bool = False
) -> int:
    """Проверяет соответствия и переносит недостающие снимки при остановленных writers.

    Не предполагает уникальность event_id в MergeTree: учитывает полное содержимое
    и число одинаковых строк. Повтор после потерянного ответа дописывает только
    недостающие строки. Для учебного объёма сравнение выполняется в памяти.

    Args:
        client: Соединение с выбранной БД ClickHouse.
        mapping: Подтверждённое соответствие всех старых учителей.
        check_only: Только проверить coverage, без DDL/INSERT.

    Returns:
        Число дописанных строк; в check_only — число обнаруженных учителей.

    Raises:
        TeacherIdMigrationError: Соответствия неверны, неполны либо сверка не прошла.
        ClickHouseError: Чтение или запись не выполнены; разрешён повтор offline.
    """
    _validate_mapping(mapping)
    ids = legacy_teacher_ids(client)
    missing = sorted(ids - mapping.keys())
    if missing:
        raise TeacherIdMigrationError(f"Missing teacher ID mapping: {missing}")
    if check_only:
        return len(ids)
    prepare_uuid_schema(client)
    if not ids:
        return 0
    columns = ",".join(COLUMN_NAMES)
    old = client.query(f"SELECT {columns} FROM lesson_snapshots").result_rows
    converted = []
    for row in old:
        values = list(row)
        values[4] = mapping[values[4]]
        converted.append(tuple(values))
    existing = Counter(
        tuple(row)
        for row in client.query(
            f"SELECT {columns} FROM lesson_snapshots_v2"
        ).result_rows
    )
    pending = list((Counter(converted) - existing).elements())
    if pending:
        # ClickHouse возвращает UTC DateTime64 без tzinfo; при INSERT драйвер
        # иначе трактует naive datetime как локальное время процесса.
        inserted = []
        for row in pending:
            values = list(row)
            for index in (1, 6, 7):
                if values[index].tzinfo is None:
                    values[index] = values[index].replace(tzinfo=UTC)
            inserted.append(values)
        client.insert("lesson_snapshots_v2", inserted, column_names=COLUMN_NAMES)
    actual = Counter(
        tuple(row)
        for row in client.query(
            f"SELECT {columns} FROM lesson_snapshots_v2"
        ).result_rows
    )
    if Counter(converted) - actual:
        raise TeacherIdMigrationError("UUID history verification failed")
    return len(pending)
