"""DDL не допускает неверные сроки и чужие SQL-FK."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def test_schema_has_local_integrity_and_server_fields():
    from homework_service.infrastructure.models.homework import HomeworkRow

    table = HomeworkRow.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "homework_assignments_issued_lesson_unique" in ddl
    assert "homework_assignments_one_due" in ddl
    assert "char_length(description) BETWEEN 1 AND 10000" in ddl
    assert not table.foreign_keys
    assert table.c.created_at.server_default is not None
    assert table.c.manual_due_datetime.nullable and table.c.due_lesson_id.nullable
