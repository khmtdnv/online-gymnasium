"""Одноразовая проверка соответствий учителей перед изменением схемы Schedule."""

import json
import re
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, Uuid, inspect, text
from sqlalchemy.engine import Connection


class TeacherIdMigrationError(Exception):
    """Переход ID небезопасен: соответствия неполны, неоднозначны или повреждены."""


class TeacherIdInventory(BaseModel):
    """Содержит только тип колонки, число записей и найденные старые ID."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    column_type: str
    lesson_count: int
    snapshot_count: int
    lesson_teacher_ids: frozenset[int]
    snapshot_teacher_ids: frozenset[int]

    @property
    def legacy_ids(self) -> frozenset[int]:
        """Возвращает все ID, включая учителей только из исторических событий."""
        return self.lesson_teacher_ids | self.snapshot_teacher_ids


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TeacherIdMigrationError("Duplicate key in teacher ID mapping")
        result[key] = value
    return result


def _validate_mapping(mapping: dict[int, UUID]) -> None:
    if any(
        type(key) is not int
        or not 1 <= key <= 2147483647
        or not isinstance(value, UUID)
        for key, value in mapping.items()
    ):
        raise TeacherIdMigrationError("Invalid teacher ID mapping")
    if len(set(mapping.values())) != len(mapping):
        raise TeacherIdMigrationError("Ambiguous UUID in teacher ID mapping")


def load_teacher_id_mapping(path: Path) -> dict[int, UUID]:
    """Читает явное соответствие int→UUID, не создавая новых идентификаторов.

    Args:
        path: Путь к одноразовому JSON-файлу перехода.

    Returns:
        Однозначные соответствия старых ID UUID пользователей Gateway.

    Raises:
        TeacherIdMigrationError: Файл недоступен, повреждён или неоднозначен.
    """
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
        )
        if not isinstance(raw, dict):
            raise TeacherIdMigrationError("Teacher ID mapping must be an object")
        mapping = {}
        for key, value in raw.items():
            if not re.fullmatch(r"[1-9][0-9]{0,9}", key) or not isinstance(value, str):
                raise TeacherIdMigrationError("Invalid teacher ID mapping")
            mapping[int(key)] = UUID(value)
    except (OSError, UnicodeError, ValueError) as exc:
        raise TeacherIdMigrationError("Cannot read teacher ID mapping") from exc
    _validate_mapping(mapping)
    return mapping


def require_teacher_id_coverage(ids: set[int], mapping: dict[int, UUID]) -> None:
    """Запрещает переход, если хотя бы одному старому ID не выбран пользователь.

    Args:
        ids: Полное множество старых ID из проверяемого хранилища.
        mapping: Предварительно подтверждённое соответствие учителей.

    Raises:
        TeacherIdMigrationError: Соответствие неоднозначно или не покрывает ID.
    """
    _validate_mapping(mapping)
    missing = sorted(ids - mapping.keys())
    if missing:
        raise TeacherIdMigrationError(f"Missing teacher ID mapping: {missing}")


def inspect_teacher_ids(bind: Connection) -> TeacherIdInventory:
    """Читает старые ID из уроков и всех снимков outbox без изменения данных.

    Args:
        bind: Соединение; CLI открывает для него read-only транзакцию.

    Returns:
        Тип колонки, числа строк и старые ID из обоих источников.

    Raises:
        TeacherIdMigrationError: Неизвестный тип колонки или повреждённый ID.
        SQLAlchemyError: Схема недоступна либо запрос не выполнен.
    """
    columns = inspect(bind).get_columns("scheduled_lessons")
    teacher_type = next(
        item["type"] for item in columns if item["name"] == "teacher_id"
    )
    if isinstance(teacher_type, Uuid):
        column_type = "uuid"
        lesson_ids = frozenset()
    elif isinstance(teacher_type, Integer):
        column_type = "integer"
        lesson_ids = frozenset(
            bind.scalars(text("SELECT DISTINCT teacher_id FROM scheduled_lessons"))
        )
        if any(type(value) is not int or value <= 0 for value in lesson_ids):
            raise TeacherIdMigrationError("Invalid legacy teacher ID in lessons")
    else:
        raise TeacherIdMigrationError("Unsupported teacher_id column type")

    snapshot_ids = set()
    for value in bind.scalars(
        text(
            "SELECT DISTINCT payload->'teacher_id' FROM outbox_events "
            "WHERE event_type = 'lesson.snapshot'"
        )
    ):
        if type(value) is int and 1 <= value <= 2147483647:
            snapshot_ids.add(value)
        elif isinstance(value, str):
            try:
                UUID(value)
            except ValueError as exc:
                raise TeacherIdMigrationError("Invalid teacher ID in snapshot") from exc
        else:
            raise TeacherIdMigrationError("Invalid teacher ID in snapshot")
    return TeacherIdInventory(
        column_type=column_type,
        lesson_count=bind.scalar(text("SELECT count(*) FROM scheduled_lessons")),
        snapshot_count=bind.scalar(
            text(
                "SELECT count(*) FROM outbox_events WHERE event_type='lesson.snapshot'"
            )
        ),
        lesson_teacher_ids=lesson_ids,
        snapshot_teacher_ids=frozenset(snapshot_ids),
    )
