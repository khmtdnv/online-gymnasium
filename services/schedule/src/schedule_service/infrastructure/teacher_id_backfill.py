"""Заполнение новой UUID-колонки без изменения остальных данных урока."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def backfill_lesson_teacher_ids(bind: Connection, mapping: dict[int, UUID]) -> None:
    """Заполняет только teacher_id_uuid через старый teacher_id и готовый mapping.

    Вызывается внутри общей транзакции после проверки соответствий и создания
    nullable UUID-колонки. Старый teacher_id ещё существует. Здесь не нужно
    создавать UUID, добавлять/удалять уроки, менять схему или выполнять commit.

    Args:
        bind: Синхронное соединение SQLAlchemy текущей миграции.
        mapping: Подтверждённые пары старый ID→UUID пользователя Gateway;
            некоторые пары могут относиться только к истории, без текущих уроков.

    Raises:
        SQLAlchemyError: Перенос данных не выполнен; общая транзакция откатится.
    """
    for old_id, teacher_id in mapping.items():
        bind.execute(
            text(
                "UPDATE scheduled_lessons SET teacher_id_uuid=CAST(:teacher AS uuid) WHERE teacher_id=:old"
            ),
            {"teacher": str(teacher_id), "old": old_id},
        )
