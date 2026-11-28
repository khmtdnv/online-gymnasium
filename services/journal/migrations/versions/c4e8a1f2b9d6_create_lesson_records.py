"""Создаёт записи урока: посещаемость и оценки.

Revision ID: c4e8a1f2b9d6
Revises: a27b35d19e80
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4e8a1f2b9d6"
down_revision = "a27b35d19e80"
branch_labels = None
depends_on = None

ATTENDANCE_STATUS = ("present", "absent_sick", "absent_excused", "absent_unexcused")
GRADE_KIND = ("oral", "written", "control")


def upgrade() -> None:
    """Добавляет таблицы посещаемости и оценок урока с их enum-типами."""
    attendance_status = postgresql.ENUM(*ATTENDANCE_STATUS, name="attendance_status")
    grade_kind = postgresql.ENUM(*GRADE_KIND, name="grade_kind")

    op.create_table(
        "lesson_attendance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("status", attendance_status, nullable=False),
        sa.Column("generator", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.PrimaryKeyConstraint("id", name="lesson_attendance_pkey"),
        sa.UniqueConstraint(
            "lesson_id", "student_id", name="lesson_attendance_lesson_student_unique"
        ),
    )
    op.create_index(
        "lesson_attendance_student_date",
        "lesson_attendance",
        ["student_id", "lesson_date"],
    )
    op.create_index(
        "lesson_attendance_class_date",
        "lesson_attendance",
        ["class_id", "lesson_date"],
    )

    op.create_table(
        "lesson_grades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("lesson_date", sa.Date(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("kind", grade_kind, nullable=False),
        sa.Column("generator", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.PrimaryKeyConstraint("id", name="lesson_grades_pkey"),
        sa.CheckConstraint("grade BETWEEN 2 AND 5", name="lesson_grades_grade_range"),
        sa.UniqueConstraint(
            "lesson_id",
            "student_id",
            "kind",
            name="lesson_grades_lesson_student_kind_unique",
        ),
    )
    op.create_index(
        "lesson_grades_student_subject_date",
        "lesson_grades",
        ["student_id", "subject_id", "lesson_date"],
    )


def downgrade() -> None:
    """Удаляет таблицы записей урока и их enum-типы."""
    op.drop_table("lesson_grades")
    op.drop_table("lesson_attendance")
    postgresql.ENUM(*GRADE_KIND, name="grade_kind").drop(op.get_bind())
    postgresql.ENUM(*ATTENDANCE_STATUS, name="attendance_status").drop(op.get_bind())
