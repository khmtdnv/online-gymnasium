"""Проверки описания таблицы классов; ограничения БД проверим отдельно."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    Uuid,
    create_engine,
    insert,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex


def test_student_class_period_has_valid_period_check() -> None:
    """Требует ограничение, запрещающее выход раньше вступления на уровне БД."""
    from journal_service.infrastructure.models.student_class_period import (
        StudentClassPeriodRow,
    )

    checks = [
        constraint
        for constraint in StudentClassPeriodRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    assert len(checks) == 1
    check = checks[0]
    assert check.name == "student_class_periods_valid_period"
    expression = str(
        check.sqltext.compile(
            dialect=postgresql.dialect(), compile_kwargs={"include_table": False}
        )
    )
    assert (
        " ".join(expression.lower().split())
        == "left_at is null or left_at >= joined_at"
    )


def test_student_class_period_has_partial_unique_current_student_index() -> None:
    """Ограничивает только открытые периоды ученика, сохраняя повторяемую историю."""
    from journal_service.infrastructure.models.student_class_period import (
        StudentClassPeriodRow,
    )

    indexes = list(StudentClassPeriodRow.__table__.indexes)
    assert len(indexes) == 1
    index = indexes[0]
    assert index.name == "student_class_periods_current_student_unique"
    assert index.unique is True
    assert list(index.columns.keys()) == ["student_id"]
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert sql.endswith("WHERE left_at IS NULL")


def test_student_class_period_columns_and_defaults() -> None:
    """Требует обязательные ссылки и начало периода; выход может отсутствовать."""
    from journal_service.infrastructure.models.student_class_period import (
        StudentClassPeriodRow,
    )

    table = StudentClassPeriodRow.__table__
    assert table.name == "student_class_periods"
    assert set(table.columns.keys()) == {
        "id",
        "student_id",
        "class_id",
        "joined_at",
        "left_at",
    }
    assert isinstance(table.c.id.type, Integer)
    assert table.c.id.primary_key
    assert table.c.id.autoincrement in (True, "auto")
    assert isinstance(table.c.student_id.type, Uuid)
    assert table.c.student_id.type.as_uuid is True
    assert isinstance(table.c.class_id.type, Integer)
    assert all(
        not table.c[name].nullable
        for name in ("id", "student_id", "class_id", "joined_at")
    )
    assert table.c.left_at.nullable is True
    for name in ("joined_at", "left_at"):
        assert isinstance(table.c[name].type, DateTime)
        assert table.c[name].type.timezone is True
    assert table.c.joined_at.server_default is not None
    assert str(table.c.joined_at.server_default.arg).lower() == "now()"
    assert table.c.left_at.server_default is None


def test_student_class_period_has_local_class_foreign_key() -> None:
    """Ссылается только на локальные классы, не связывает БД разных сервисов."""
    from journal_service.infrastructure.models.student_class_period import (
        StudentClassPeriodRow,
    )

    table = StudentClassPeriodRow.__table__
    assert len(table.foreign_keys) == 1
    foreign_key = next(iter(table.foreign_keys))
    assert foreign_key.parent.name == "class_id"
    assert foreign_key.target_fullname == "classes.id"
    assert foreign_key.ondelete is None
    assert not table.c.student_id.foreign_keys


def test_classes_columns_have_required_types_and_nullability() -> None:
    """Не допускает потерю обязательного поля или неверный SQL-тип."""
    from journal_service.infrastructure.models.school_class import ClassRow

    table = ClassRow.__table__

    assert table.name == "classes"
    assert set(table.columns.keys()) == {"id", "name", "study_year", "created_at"}
    assert all(not column.nullable for column in table.columns)
    assert isinstance(table.c.id.type, Integer)
    assert table.c.id.primary_key
    assert isinstance(table.c.name.type, String)
    assert table.c.name.type.length == 64
    assert isinstance(table.c.study_year.type, Integer)


def test_classes_creation_time_is_generated_by_database_with_timezone() -> None:
    """Требует серверное время вместо обязательной передачи его приложением."""
    from journal_service.infrastructure.models.school_class import ClassRow

    column = ClassRow.__table__.c.created_at

    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True
    assert column.server_default is not None
    assert str(column.server_default.arg).lower() == "now()"


def test_classes_declare_unique_name_within_study_year() -> None:
    """Требует уникальность пары, а не запрет повторять имя в разные годы."""
    from journal_service.infrastructure.models.school_class import ClassRow

    constraints = [
        constraint
        for constraint in ClassRow.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert len(constraints) == 1
    constraint = constraints[0]
    assert constraint.name == "classes_name_study_year_unique"
    assert set(constraint.columns.keys()) == {"study_year", "name"}


@pytest.mark.parametrize(
    ("study_year", "accepted"),
    [(1900, True), (2026, True), (9998, True), (1899, False), (9999, False)],
)
def test_classes_year_check_enforces_boundaries_in_sqlite(
    study_year: int, accepted: bool
) -> None:
    """Изолированно проверяет условие года; полную таблицу проверим в PostgreSQL."""
    from journal_service.infrastructure.models.school_class import ClassRow

    table = ClassRow.__table__.to_metadata(MetaData())
    # Копия только для теста года: SQLite не поддерживает функции проверки имени.
    for constraint in list(table.constraints):
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name != "classes_valid_study_year"
        ):
            table.constraints.remove(constraint)
    engine = create_engine("sqlite://")
    try:
        table.create(engine)
        statement = insert(table).values(
            name="7А", study_year=study_year, created_at=datetime.now(UTC)
        )
        with engine.begin() as connection:
            if accepted:
                connection.execute(statement)
            else:
                with pytest.raises(IntegrityError):
                    connection.execute(statement)
    finally:
        engine.dispose()


def test_journal_outbox_has_required_storage_contract() -> None:
    """Требует UUID ключ, JSONB, серверную дату и необязательную дату публикации."""
    from sqlalchemy import DateTime
    from sqlalchemy.dialects.postgresql import JSONB, UUID

    from journal_service.infrastructure.models.outbox_event import JournalOutboxEventRow

    table = JournalOutboxEventRow.__table__
    assert table.name == "journal_event_outbox"
    assert set(table.columns.keys()) == {
        "event_id",
        "envelope",
        "created_at",
        "published_at",
    }
    assert isinstance(table.c.event_id.type, UUID)
    assert table.c.event_id.primary_key
    assert isinstance(table.c.envelope.type, JSONB)
    assert not table.c.envelope.nullable
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone
    assert not table.c.created_at.nullable
    assert table.c.created_at.server_default is not None
    assert table.c.published_at.type.timezone
    assert table.c.published_at.nullable
