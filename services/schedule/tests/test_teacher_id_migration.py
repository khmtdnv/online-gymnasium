"""Проверяет одноразовое соответствие старых ID настоящим UUID, без угадывания."""

from uuid import UUID

import pytest

TEACHER_A = UUID("8df96b7a-7d30-44e7-b577-f6581300e101")
TEACHER_B = UUID("8df96b7a-7d30-44e7-b577-f6581300e102")


def test_load_mapping_preserves_explicit_identity(tmp_path):
    from schedule_service.infrastructure.teacher_id_migration import (
        load_teacher_id_mapping,
    )

    path = tmp_path / "mapping.json"
    path.write_text(f'{{"42":"{TEACHER_A}","77":"{TEACHER_B}"}}')
    assert load_teacher_id_mapping(path) == {42: TEACHER_A, 77: TEACHER_B}


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        "not json",
        f'{{"0":"{TEACHER_A}"}}',
        f'{{"-1":"{TEACHER_A}"}}',
        f'{{"true":"{TEACHER_A}"}}',
        f'{{"01":"{TEACHER_A}"}}',
        f'{{"2147483648":"{TEACHER_A}"}}',
        '{"42":42}',
        '{"42":null}',
        '{"42":"not-a-uuid"}',
        f'{{"42":"{TEACHER_A}","42":"{TEACHER_B}"}}',
        f'{{"42":"{TEACHER_A}","77":"{TEACHER_A}"}}',
    ],
)
def test_mapping_rejects_invalid_or_ambiguous_identity(tmp_path, raw):
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
        load_teacher_id_mapping,
    )

    path = tmp_path / "mapping.json"
    path.write_text(raw)
    with pytest.raises(TeacherIdMigrationError):
        load_teacher_id_mapping(path)


def test_unreadable_mapping_has_safe_error(tmp_path):
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
        load_teacher_id_mapping,
    )

    with pytest.raises(TeacherIdMigrationError, match="mapping"):
        load_teacher_id_mapping(tmp_path / "absent.json")


def test_missing_historical_teacher_is_not_replaced_by_random_uuid():
    from schedule_service.infrastructure.teacher_id_migration import (
        TeacherIdMigrationError,
        require_teacher_id_coverage,
    )

    with pytest.raises(TeacherIdMigrationError, match="77"):
        require_teacher_id_coverage({42, 77}, {42: TEACHER_A})


def test_full_mapping_and_empty_database_are_allowed():
    from schedule_service.infrastructure.teacher_id_migration import (
        require_teacher_id_coverage,
    )

    assert require_teacher_id_coverage({42}, {42: TEACHER_A}) is None
    assert require_teacher_id_coverage(set(), {}) is None
