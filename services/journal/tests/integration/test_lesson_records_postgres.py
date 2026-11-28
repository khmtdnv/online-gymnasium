"""Проверяет записи урока настоящим PostgreSQL: замена, инварианты, агрегаты."""

import asyncio
from datetime import date
from uuid import UUID

import pytest
from conftest import database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import journal_service.application.lesson_records as lesson_records_module
from journal_service.application.lesson_records import (
    AttendanceEntry,
    GetLastEntryDateHandler,
    GetSubjectAveragesHandler,
    GradeEntry,
    LessonContext,
    ListLessonEntriesHandler,
    ListStudentDiaryEntriesHandler,
    RecordLessonEntriesCommand,
    RecordLessonEntriesHandler,
)
from journal_service.domain.lesson_records import AttendanceStatus, GradeKind

TEACHER_ID = UUID("bbbbbbbb-0000-4000-8000-000000000001")
STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
OTHER_STUDENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000002")
TODAY = date(2026, 11, 27)
LESSON_DATE = date(2026, 11, 15)


@pytest.fixture
def fixed_today(monkeypatch) -> None:
    """Закрепляет школьную дату для детерминизма проверок четверти."""
    monkeypatch.setattr(lesson_records_module, "school_today", lambda: TODAY)


async def create_class_with_roster(connection) -> tuple[int, int, int]:
    """Создаёт класс и два открытых периода учеников напрямую в БД.

    Args:
        connection: Соединение внутри текущей тестовой транзакции.

    Returns:
        ID класса, ID периодов первого и второго ученика.
    """
    class_id = (
        await connection.execute(
            text(
                "INSERT INTO classes (name, study_year)"
                " VALUES ('7А', 2026) RETURNING id"
            )
        )
    ).scalar_one()
    first = (
        await connection.execute(
            text(
                "INSERT INTO student_class_periods (student_id, class_id, joined_at)"
                " VALUES (:student, :class_id, '2026-09-01 09:00:00+00')"
                " RETURNING id"
            ),
            {"student": STUDENT_ID, "class_id": class_id},
        )
    ).scalar_one()
    second = (
        await connection.execute(
            text(
                "INSERT INTO student_class_periods (student_id, class_id, joined_at)"
                " VALUES (:student, :class_id, '2026-09-01 09:00:00+00')"
                " RETURNING id"
            ),
            {"student": OTHER_STUDENT_ID, "class_id": class_id},
        )
    ).scalar_one()
    return class_id, first, second


def make_command(
    class_id: int,
    *,
    attendance: list[AttendanceEntry],
    grades: list[GradeEntry],
) -> RecordLessonEntriesCommand:
    """Собирает команду замены записей урока."""
    return RecordLessonEntriesCommand(
        lesson_id=42,
        context=LessonContext(
            class_id=class_id,
            subject_id=3,
            lesson_date=LESSON_DATE,
            status="planned",
            teacher_id=TEACHER_ID,
        ),
        attendance=attendance,
        grades=grades,
    )


def test_replace_inserts_updates_and_deletes(database_url: str, fixed_today) -> None:
    """Пакет-замена вставляет, обновляет и удаляет строки одного урока."""

    async def run() -> None:
        async with database(database_url) as (_engine, uow_factory):
            async with _engine.begin() as connection:
                class_id, _, _ = await create_class_with_roster(connection)

            handler = RecordLessonEntriesHandler(uow_factory)
            first = AttendanceEntry(
                student_id=STUDENT_ID, status=AttendanceStatus.PRESENT
            )
            second = AttendanceEntry(
                student_id=OTHER_STUDENT_ID, status=AttendanceStatus.ABSENT_SICK
            )
            grade = GradeEntry(student_id=STUDENT_ID, kind=GradeKind.ORAL, grade=5)

            result = await handler.handle(
                make_command(class_id, attendance=[first, second], grades=[grade]),
                actor_id=TEACHER_ID,
            )
            assert len(result.attendance) == 2
            assert len(result.grades) == 1
            assert result.grades[0].student_id == STUDENT_ID
            assert result.attendance[0].created_at is not None

            reader = ListLessonEntriesHandler(uow_factory)
            state = await reader.handle(42)
            assert {item.status for item in state.attendance} == {
                AttendanceStatus.PRESENT,
                AttendanceStatus.ABSENT_SICK,
            }

            updated_first = AttendanceEntry(
                student_id=STUDENT_ID, status=AttendanceStatus.ABSENT_EXCUSED
            )
            result = await handler.handle(
                make_command(class_id, attendance=[updated_first], grades=[]),
                actor_id=TEACHER_ID,
            )
            assert len(result.attendance) == 1
            assert result.attendance[0].status is AttendanceStatus.ABSENT_EXCUSED
            assert result.grades == []

            state = await reader.handle(42)
            assert [item.student_id for item in state.attendance] == [STUDENT_ID]
            assert state.grades == []

    asyncio.run(run())


def test_unique_and_check_constraints(database_url: str) -> None:
    """База отвергает дубль посещаемости и оценку вне шкалы."""

    async def run() -> None:
        async with database(database_url) as (engine, _uow_factory):
            async with engine.begin() as connection:
                class_id, _, _ = await create_class_with_roster(connection)

            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO lesson_attendance"
                        " (lesson_id, lesson_date, class_id, student_id, status,"
                        " author_id) VALUES (50, '2026-11-16', :class_id, :student,"
                        " 'present', :author)"
                    ),
                    {
                        "class_id": class_id,
                        "student": STUDENT_ID,
                        "author": TEACHER_ID,
                    },
                )

            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO lesson_attendance"
                            " (lesson_id, lesson_date, class_id, student_id, status,"
                            " author_id) VALUES (50, '2026-11-16', :class_id,"
                            " :student, 'present', :author)"
                        ),
                        {
                            "class_id": class_id,
                            "student": STUDENT_ID,
                            "author": TEACHER_ID,
                        },
                    )

            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO lesson_grades"
                            " (lesson_id, lesson_date, class_id, subject_id,"
                            " student_id, grade, kind, author_id)"
                            " VALUES (50, '2026-11-16', :class_id, 3, :student, 1,"
                            " 'oral', :author)"
                        ),
                        {
                            "class_id": class_id,
                            "student": STUDENT_ID,
                            "author": TEACHER_ID,
                        },
                    )

    asyncio.run(run())


def test_members_on_date_respects_period_boundaries(database_url: str) -> None:
    """Состав на дату учитывает календарные границы периода."""

    async def run() -> None:
        async with database(database_url) as (engine, uow_factory):
            async with engine.begin() as connection:
                class_id = (
                    await connection.execute(
                        text(
                            "INSERT INTO classes (name, study_year)"
                            " VALUES ('8А', 2026) RETURNING id"
                        )
                    )
                ).scalar_one()
                await connection.execute(
                    text(
                        "INSERT INTO student_class_periods"
                        " (student_id, class_id, joined_at, left_at)"
                        " VALUES (:student, :class_id, '2026-09-10 09:00:00+00',"
                        " '2026-11-20 09:00:00+00')"
                    ),
                    {"student": STUDENT_ID, "class_id": class_id},
                )

            async with uow_factory() as uow:
                repository = uow.class_periods
                before_join = await repository.list_members_on_date(
                    class_id, date(2026, 9, 5)
                )
                on_join = await repository.list_members_on_date(
                    class_id, date(2026, 9, 10)
                )
                inside = await repository.list_members_on_date(
                    class_id, date(2026, 11, 19)
                )
                after_left = await repository.list_members_on_date(
                    class_id, date(2026, 11, 25)
                )

            assert before_join == []
            assert len(on_join) == 1
            assert len(inside) == 1
            assert after_left == []

    asyncio.run(run())


def test_averages_and_last_entry_date(database_url: str, fixed_today) -> None:
    """Средние группируются по предмету; якорь — максимум дат записей."""

    async def run() -> None:
        async with database(database_url) as (engine, uow_factory):
            async with engine.begin() as connection:
                class_id, _, _ = await create_class_with_roster(connection)

            handler = RecordLessonEntriesHandler(uow_factory)
            command = make_command(
                class_id,
                attendance=[
                    AttendanceEntry(
                        student_id=STUDENT_ID, status=AttendanceStatus.PRESENT
                    )
                ],
                grades=[
                    GradeEntry(student_id=STUDENT_ID, kind=GradeKind.ORAL, grade=5),
                    GradeEntry(student_id=STUDENT_ID, kind=GradeKind.WRITTEN, grade=4),
                ],
            )
            await handler.handle(command, actor_id=TEACHER_ID)

            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO lesson_grades"
                        " (lesson_id, lesson_date, class_id, subject_id, student_id,"
                        " grade, kind, author_id)"
                        " VALUES (43, '2026-11-17', :class_id, 4, :student, 3,"
                        " 'control', :author)"
                    ),
                    {
                        "class_id": class_id,
                        "student": STUDENT_ID,
                        "author": TEACHER_ID,
                    },
                )

            averages = await GetSubjectAveragesHandler(uow_factory).handle(
                STUDENT_ID, 2
            )
            by_subject = {item.subject_id: item for item in averages}
            assert by_subject[3].grade_count == 2
            assert float(by_subject[3].average) == 4.5
            assert by_subject[3].quarter_grade == 5
            assert by_subject[4].grade_count == 1
            assert by_subject[4].quarter_grade == 3

            anchor = await GetLastEntryDateHandler(uow_factory).handle(STUDENT_ID)
            assert anchor.last_entry_date == date(2026, 11, 17)

            entries = await ListStudentDiaryEntriesHandler(uow_factory).handle(
                STUDENT_ID, date(2026, 11, 16), date(2026, 11, 18)
            )
            assert [item.kind for item in entries.grades] == [GradeKind.CONTROL]

    asyncio.run(run())


def test_teacher_rewrite_converts_generator_rows(
    database_url: str, fixed_today
) -> None:
    """Правка учителем переводит генераторную строку в живую."""

    async def run() -> None:
        async with database(database_url) as (engine, uow_factory):
            async with engine.begin() as connection:
                class_id, _, _ = await create_class_with_roster(connection)

            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO lesson_attendance"
                        " (lesson_id, lesson_date, class_id, student_id, status,"
                        " author_id, generator)"
                        " VALUES (60, '2026-11-18', :class_id, :student, 'present',"
                        " :author, true)"
                    ),
                    {
                        "class_id": class_id,
                        "student": STUDENT_ID,
                        "author": TEACHER_ID,
                    },
                )

            handler = RecordLessonEntriesHandler(uow_factory)
            result = await handler.handle(
                make_command(
                    class_id,
                    attendance=[
                        AttendanceEntry(
                            student_id=STUDENT_ID, status=AttendanceStatus.PRESENT
                        )
                    ],
                    grades=[
                        GradeEntry(
                            student_id=STUDENT_ID, kind=GradeKind.CONTROL, grade=4
                        )
                    ],
                ),
                actor_id=TEACHER_ID,
            )
            assert result.attendance[0].generator is False
            assert result.attendance[0].created_at is not None
            assert result.attendance[0].updated_at is not None

    asyncio.run(run())
