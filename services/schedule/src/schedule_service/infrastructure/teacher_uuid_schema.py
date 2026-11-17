"""Переводит teacher_id и историю outbox по явным соответствиям одной транзакцией."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from schedule_service.infrastructure.teacher_id_backfill import (
    backfill_lesson_teacher_ids,
)
from schedule_service.infrastructure.teacher_id_migration import (
    TeacherIdMigrationError,
    inspect_teacher_ids,
    require_teacher_id_coverage,
)


def upgrade_teacher_ids(bind: Connection, mapping: dict[int, UUID]) -> None:
    """Меняет ссылки на учителей одной транзакцией, не переписывая ID уроков.

    Вызывается ревизией Alembic, не обычным HTTP-запросом.
    Блокировки рассчитаны на согласованный offline-переход, не online DDL.

    Args:
        bind: Соединение внутри транзакции владельца; commit здесь не выполняется.
        mapping: Полные однозначные соответствия старых пользователей.

    Raises:
        TeacherIdMigrationError: Нет транзакции, схема не старая, соответствия
            неполны либо backfill заполнил данные неверно.
        SQLAlchemyError: База отклонила DDL/запись; вызывающий откатывает транзакцию.
    """
    if not bind.in_transaction():
        raise TeacherIdMigrationError("Teacher migration requires a transaction")
    bind.execute(
        text("LOCK TABLE scheduled_lessons, outbox_events IN ACCESS EXCLUSIVE MODE")
    )
    inventory = inspect_teacher_ids(bind)
    if inventory.column_type != "integer":
        raise TeacherIdMigrationError("Teacher IDs are already UUID")
    require_teacher_id_coverage(set(inventory.legacy_ids), mapping)

    bind.execute(text("ALTER TABLE scheduled_lessons ADD COLUMN teacher_id_uuid uuid"))
    if inventory.lesson_count:
        backfill_lesson_teacher_ids(bind, mapping)
    _check_backfill(bind, mapping)
    _convert_snapshot_ids(bind, mapping)
    bind.execute(
        text(
            "ALTER TABLE scheduled_lessons "
            "DROP CONSTRAINT scheduled_lessons_no_teacher_overlap"
        )
    )
    bind.execute(text("ALTER TABLE scheduled_lessons DROP COLUMN teacher_id"))
    bind.execute(
        text(
            "ALTER TABLE scheduled_lessons RENAME COLUMN teacher_id_uuid TO teacher_id"
        )
    )
    bind.execute(
        text("ALTER TABLE scheduled_lessons ALTER COLUMN teacher_id SET NOT NULL")
    )
    bind.execute(
        text(
            "ALTER TABLE scheduled_lessons ADD CONSTRAINT "
            "scheduled_lessons_no_teacher_overlap EXCLUDE USING gist "
            "(teacher_id WITH =, tstzrange(starts_at,ends_at,'[)') WITH &&) "
            "WHERE (status = 'planned')"
        )
    )


def _check_backfill(bind: Connection, mapping: dict[int, UUID]) -> None:
    missing = bind.scalar(
        text("SELECT count(*) FROM scheduled_lessons WHERE teacher_id_uuid IS NULL")
    )
    if missing:
        raise TeacherIdMigrationError("Incomplete teacher ID backfill")
    for old_id, teacher_id in mapping.items():
        mismatched = bind.scalar(
            text(
                "SELECT count(*) FROM scheduled_lessons WHERE teacher_id=:old_id "
                "AND teacher_id_uuid IS DISTINCT FROM CAST(:teacher_id AS uuid)"
            ),
            {"old_id": old_id, "teacher_id": str(teacher_id)},
        )
        if mismatched:
            raise TeacherIdMigrationError("Incorrect teacher ID backfill")


def _convert_snapshot_ids(bind: Connection, mapping: dict[int, UUID]) -> None:
    for old_id, teacher_id in mapping.items():
        bind.execute(
            text(
                "UPDATE outbox_events SET payload = jsonb_set("
                "payload,'{teacher_id}',to_jsonb(CAST(:teacher_id AS text)),false) "
                "WHERE event_type='lesson.snapshot' "
                "AND payload->'teacher_id'=CAST(:old_id AS jsonb)"
            ),
            {"old_id": str(old_id), "teacher_id": str(teacher_id)},
        )


def downgrade_teacher_ids(bind: Connection, mapping: dict[int, UUID]) -> None:
    """Возвращает integer только при полном подтверждённом обратном соответствии.

    Args:
        bind: Соединение внутри общей транзакции миграции.
        mapping: Однозначные пары старый integer→UUID для всех сохранённых данных.

    Raises:
        TeacherIdMigrationError: Нет транзакции, колонка не UUID либо неизвестен
            старый integer хотя бы одного пользователя, включая историю.
        SQLAlchemyError: Изменение схемы или данных не выполнено.
    """
    if not bind.in_transaction():
        raise TeacherIdMigrationError("Teacher migration requires a transaction")
    require_teacher_id_coverage(set(), mapping)
    bind.execute(
        text("LOCK TABLE scheduled_lessons, outbox_events IN ACCESS EXCLUSIVE MODE")
    )
    if inspect_teacher_ids(bind).column_type != "uuid":
        raise TeacherIdMigrationError("Teacher IDs are not UUID")
    found = set(bind.scalars(text("SELECT DISTINCT teacher_id FROM scheduled_lessons")))
    for value in bind.scalars(
        text(
            "SELECT DISTINCT payload->>'teacher_id' FROM outbox_events WHERE event_type='lesson.snapshot'"
        )
    ):
        try:
            found.add(UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise TeacherIdMigrationError("Invalid snapshot UUID") from exc
    inverse = {value: key for key, value in mapping.items()}
    if found - inverse.keys():
        raise TeacherIdMigrationError("Missing reverse teacher ID mapping")
    bind.execute(
        text("ALTER TABLE scheduled_lessons ADD COLUMN teacher_id_integer integer")
    )
    for teacher_id in found:
        parameters = {"teacher": str(teacher_id), "old": inverse[teacher_id]}
        bind.execute(
            text(
                "UPDATE scheduled_lessons SET teacher_id_integer=:old WHERE teacher_id=CAST(:teacher AS uuid)"
            ),
            parameters,
        )
        bind.execute(
            text(
                "UPDATE outbox_events SET payload=jsonb_set(payload,'{teacher_id}',to_jsonb(CAST(:old AS integer)),false) WHERE event_type='lesson.snapshot' AND payload->>'teacher_id'=:teacher"
            ),
            parameters,
        )
    bind.execute(
        text(
            "ALTER TABLE scheduled_lessons DROP CONSTRAINT scheduled_lessons_no_teacher_overlap"
        )
    )
    bind.execute(text("ALTER TABLE scheduled_lessons DROP COLUMN teacher_id"))
    bind.execute(
        text(
            "ALTER TABLE scheduled_lessons RENAME COLUMN teacher_id_integer TO teacher_id"
        )
    )
    bind.execute(
        text("ALTER TABLE scheduled_lessons ALTER COLUMN teacher_id SET NOT NULL")
    )
    bind.execute(
        text(
            "ALTER TABLE scheduled_lessons ADD CONSTRAINT scheduled_lessons_no_teacher_overlap EXCLUDE USING gist (teacher_id WITH =, tstzrange(starts_at,ends_at,'[)') WITH &&) WHERE (status = 'planned')"
        )
    )
