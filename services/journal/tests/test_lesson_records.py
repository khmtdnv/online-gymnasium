"""Проверяет доменные правила посещаемости и оценок за урок."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from journal_service.domain.lesson_records import (
    AttendanceStatus,
    GradeKind,
    LessonAttendance,
    LessonGrade,
)

TEACHER_ID = UUID("bbbbbbbb-0000-4000-8000-000000000001")
STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
LESSON_DATE = date(2026, 11, 15)
CREATED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def make_attendance(
    status: AttendanceStatus = AttendanceStatus.PRESENT,
) -> LessonAttendance:
    """Собирает валидную посещаемость для тестов."""
    return LessonAttendance(
        lesson_id=42,
        lesson_date=LESSON_DATE,
        class_id=7,
        student_id=STUDENT_ID,
        status=status,
        author_id=TEACHER_ID,
    )


def make_grade(grade: int = 5, kind: GradeKind = GradeKind.ORAL) -> LessonGrade:
    """Собирает валидную оценку для тестов."""
    return LessonGrade(
        lesson_id=42,
        lesson_date=LESSON_DATE,
        class_id=7,
        subject_id=3,
        student_id=STUDENT_ID,
        grade=grade,
        kind=kind,
        author_id=TEACHER_ID,
    )


def test_valid_attendance_defaults() -> None:
    """По умолчанию строка живая и без серверных полей."""
    item = make_attendance()
    assert item.generator is False
    assert item.id is None
    assert item.is_present is True


@pytest.mark.parametrize(
    "status",
    list(AttendanceStatus)[:-1],
)
def test_absent_statuses_are_not_present(status: AttendanceStatus) -> None:
    """Только PRESENT считается присутствием."""
    item = make_attendance(status=status)
    assert item.is_present is (status is AttendanceStatus.PRESENT)


@pytest.mark.parametrize("lesson_id", [0, -1])
def test_attendance_rejects_bad_lesson_id(lesson_id: int) -> None:
    """Посещаемость требует положительный ID урока."""
    with pytest.raises(ValueError):
        LessonAttendance(
            lesson_id=lesson_id,
            lesson_date=LESSON_DATE,
            class_id=7,
            student_id=STUDENT_ID,
            status=AttendanceStatus.PRESENT,
            author_id=TEACHER_ID,
        )


@pytest.mark.parametrize("class_id", [0, -1])
def test_attendance_rejects_bad_class_id(class_id: int) -> None:
    """Посещаемость требует положительный ID класса."""
    with pytest.raises(ValueError):
        LessonAttendance(
            lesson_id=42,
            lesson_date=LESSON_DATE,
            class_id=class_id,
            student_id=STUDENT_ID,
            status=AttendanceStatus.PRESENT,
            author_id=TEACHER_ID,
        )


def test_attendance_rejects_foreign_status() -> None:
    """Посещаемость требует член enum, а не строку."""
    with pytest.raises(TypeError):
        LessonAttendance(
            lesson_id=42,
            lesson_date=LESSON_DATE,
            class_id=7,
            student_id=STUDENT_ID,
            status="present",
            author_id=TEACHER_ID,
        )


@pytest.mark.parametrize("grade", [1, 0, 6, -2])
def test_grade_rejects_out_of_scale(grade: int) -> None:
    """Оценка ограничена шкалой 2–5."""
    with pytest.raises(ValueError):
        make_grade(grade=grade)


@pytest.mark.parametrize("subject_id", [0, -1])
def test_grade_rejects_bad_subject_id(subject_id: int) -> None:
    """Оценка требует положительный ID предмета."""
    with pytest.raises(ValueError):
        LessonGrade(
            lesson_id=42,
            lesson_date=LESSON_DATE,
            class_id=7,
            subject_id=subject_id,
            student_id=STUDENT_ID,
            grade=5,
            kind=GradeKind.ORAL,
            author_id=TEACHER_ID,
        )


def test_grade_rejects_foreign_kind() -> None:
    """Оценка требует член enum типа, а не строку."""
    with pytest.raises(TypeError):
        LessonGrade(
            lesson_id=42,
            lesson_date=LESSON_DATE,
            class_id=7,
            subject_id=3,
            student_id=STUDENT_ID,
            grade=5,
            kind="oral",
            author_id=TEACHER_ID,
        )


@pytest.mark.parametrize("factory", [make_attendance, make_grade])
def test_entries_reject_naive_timestamps(factory) -> None:
    """Серверные метки времени обязаны иметь смещение UTC."""
    with pytest.raises(ValueError):
        factory().__class__(
            **{
                **factory().__dict__,
                "created_at": datetime(2026, 11, 15, 12, 0),  # noqa: DTZ001
            }
        )


def test_saved_entries_keep_server_fields() -> None:
    """Сохранённые записи сохраняют назначенные базой поля."""
    attendance = LessonAttendance(
        lesson_id=42,
        lesson_date=LESSON_DATE,
        class_id=7,
        student_id=STUDENT_ID,
        status=AttendanceStatus.ABSENT_SICK,
        author_id=TEACHER_ID,
        id=9,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    grade = LessonGrade(
        lesson_id=42,
        lesson_date=LESSON_DATE,
        class_id=7,
        subject_id=3,
        student_id=STUDENT_ID,
        grade=4,
        kind=GradeKind.CONTROL,
        author_id=TEACHER_ID,
        id=11,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    assert attendance.id == 9
    assert grade.kind is GradeKind.CONTROL
    assert grade.grade == 4
