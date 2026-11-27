"""Expands the local demo school: grades 1-11 lines A-D, staff, students.

Run: python3 tools/create_demo_data.py --large --apply
Reuses the existing demo accounts and classes, never deletes data.
Teacher accounts are created only for the subjects applicable to the
grade (SUBJECT_GRADES x GRADE_CURRICULUM of tools/demo_curriculum.py);
unused legacy accounts of non-applicable subjects stay (inert) - there
is no user deletion API.

The yearly timetable is not built here anymore: create_demo_data runs
the year rebuild (tools/rebuild_demo_timetable.rebuild_year) and the
homework scenarios right after this step.
"""

from __future__ import annotations

import json
import subprocess

from create_demo_data import ROOT, DemoError, ensure_user
from demo_curriculum import GRADE_CURRICULUM

LETTERS = ("А", "Б", "В", "Г", "Д")
CODES = ("a", "b", "v", "g", "d")
STUDENTS_PER_CLASS = 10
SUBJECTS = (
    (1, "Математика"),
    (2, "Русский язык"),
    (1001, "Литература"),
    (1002, "Окружающий мир"),
    (1003, "История"),
    (1004, "Английский язык"),
    (1005, "Биология"),
    (1006, "Физика"),
    (1007, "География"),
    (1008, "Информатика"),
    (1009, "Физическая культура"),
)
FIRST_NAMES = (
    "Артём",
    "Иван",
    "Максим",
    "Даниил",
    "Никита",
    "Анастасия",
    "Мария",
    "София",
    "Александра",
    "Екатерина",
)
LAST_NAMES = (
    "Иванов",
    "Петров",
    "Смирнов",
    "Соколов",
    "Кузнецов",
    "Попов",
    "Васильев",
    "Новиков",
    "Морозов",
    "Волков",
    "Алексеев",
    "Орлов",
    "Лебедев",
    "Козлов",
    "Киселёв",
)

# Mathematics (id 1) is taught by the class line teacher.
CLASS_TEACHER_SUBJECT_ID = 1


def emails(grade: int, code: str, index: int | None = None) -> str:
    prefix = f"{grade:02}" + ("" if code == "a" else f".{code}")
    return (
        f"student{prefix}.{index}@demo.og.test"
        if index
        else f"teacher{prefix}@demo.og.test"
    )


def subject_teacher_email(grade: int, code: str, subject_id: int) -> str:
    """The class line teacher stays the mathematics teacher."""
    if subject_id == CLASS_TEACHER_SUBJECT_ID:
        return emails(grade, code)
    return f"teacher{grade:02}.{code}.subject{subject_id}@demo.og.test"


def applicable_subject_ids(grade: int) -> list[int]:
    """Subject ids the grade actually studies per the curriculum table.

    Hours come from GRADE_CURRICULUM (which check_feasibility keeps in
    sync with the SUBJECT_GRADES applicability); mathematics is served
    by the class line teachers and gets no separate subject account.
    """
    hours = GRADE_CURRICULUM[grade]
    catalog = {name: subject_id for subject_id, name in SUBJECTS}
    unknown = set(hours) - set(catalog)
    if unknown:
        raise DemoError(f"Предметы таблицы часов вне каталога школы: {sorted(unknown)}")
    return [
        subject_id
        for subject_id, name in SUBJECTS
        if name in hours and subject_id != CLASS_TEACHER_SUBJECT_ID
    ]


def expansion_accounts() -> list[dict]:
    accounts = []
    for grade in range(1, 12):
        subjects = applicable_subject_ids(grade)
        for branch, code in enumerate(CODES):
            surname = LAST_NAMES[(grade - 1 + branch * 3) % len(LAST_NAMES)]
            accounts.append(
                {
                    "email": emails(grade, code),
                    "role": "teacher",
                    "first_name": "Александр",
                    "last_name": surname,
                    "middle_name": "Сергеевич",
                }
            )
            for subject_id in subjects:
                accounts.append(
                    {
                        "email": subject_teacher_email(grade, code, subject_id),
                        "role": "teacher",
                        "first_name": FIRST_NAMES[
                            (subject_id + branch) % len(FIRST_NAMES)
                        ],
                        "last_name": LAST_NAMES[
                            (subject_id + grade + branch) % len(LAST_NAMES)
                        ],
                        "middle_name": "",
                    }
                )
            for index, name in enumerate(FIRST_NAMES, 1):
                student_surname = LAST_NAMES[
                    (grade * 3 + branch * 7 + index) % len(LAST_NAMES)
                ]
                if index > 5:
                    student_surname += "а"
                accounts.append(
                    {
                        "email": emails(grade, code, index),
                        "role": "student",
                        "first_name": name,
                        "last_name": student_surname,
                        "middle_name": "Сергеевна" if index > 5 else "Сергеевич",
                    }
                )
    return accounts


def apply_expansion(gateway, journal, schedule, study_year):
    """Creates the missing demo staff, classes and students; never deletes.

    Lessons are not touched here: the study-year timetable is rebuilt by
    tools/rebuild_demo_timetable.rebuild_year right after this step
    (see create_demo_data.main), and the homework scenarios are created
    on top of it. The report keeps the stored year fingerprint so the
    following year run can stay empty.
    """
    accounts = expansion_accounts()
    users = {
        u["email"]: u for u in gateway.request("GET", "/internal/backoffice/users")
    }
    for i, account in enumerate(accounts, 1):
        ensure_user(gateway, account, users)
        if i % 100 == 0:
            print(f"Учётные записи: {i}/{len(accounts)}", flush=True)

    # Математику (CLASS_TEACHER_SUBJECT_ID) ведут классные руководители
    # линий, остальные предметы — предметные аккаунты применимых предметов;
    # разрешённый список покрывает обе группы, иначе set_subject_names
    # отклоняет уроки года как «недемо-уроки».
    allowed_teacher_ids = [
        users[emails(grade, code)]["id"] for grade in range(1, 12) for code in CODES
    ] + [
        users[subject_teacher_email(grade, code, subject_id)]["id"]
        for grade in range(1, 12)
        for code in CODES
        for subject_id in applicable_subject_ids(grade)
    ]
    subject_config = {
        "subjects": [{"id": id, "name": name} for id, name in SUBJECTS],
        "allowed_teacher_ids": allowed_teacher_ids,
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "schedule-api",
            "/app/.venv/bin/python",
            "-m",
            "schedule_service.set_subject_names",
        ],
        cwd=ROOT,
        input=json.dumps(subject_config),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise DemoError(
            "Не удалось безопасно подготовить названия предметов: проверьте конфликты со существующими уроками."
        )

    existing = []
    offset = 0
    while True:
        page = journal.request(
            "GET",
            f"/internal/classes?study_year={study_year}&limit=100&offset={offset}",
        )
        existing.extend(page)
        if len(page) < 100:
            break
        offset += 100
    by_name = {row["name"]: row for row in existing}
    summary = []
    for grade in range(1, 12):
        subjects = applicable_subject_ids(grade)
        for letter, code in zip(LETTERS, CODES, strict=True):
            name = f"{grade}{letter}"
            school_class = by_name.get(name)
            if school_class is None:
                school_class = journal.request(
                    "POST",
                    "/internal/classes",
                    {"name": name, "study_year": study_year},
                    ok=(201,),
                )
                by_name[name] = school_class
            class_id = school_class["id"]
            teacher = users[emails(grade, code)]
            journal.request(
                "PUT",
                f"/internal/teachers/{teacher['id']}/classes/{class_id}",
                ok=(201, 204),
            )
            for subject_id in subjects:
                subject_teacher = users[subject_teacher_email(grade, code, subject_id)]
                journal.request(
                    "PUT",
                    f"/internal/teachers/{subject_teacher['id']}/classes/{class_id}",
                    ok=(201, 204),
                )
            for index in range(1, STUDENTS_PER_CLASS + 1):
                student = users[emails(grade, code, index)]
                journal.request(
                    "PUT",
                    f"/internal/students/{student['id']}/current-class-period",
                    {"class_id": class_id},
                    ok=(200, 201),
                )
            summary.append(
                {
                    "name": name,
                    "id": class_id,
                    "teacher": teacher["email"],
                    "students": [
                        emails(grade, code, i) for i in range(1, STUDENTS_PER_CLASS + 1)
                    ],
                }
            )
            print(
                f"{name}: {STUDENTS_PER_CLASS} учеников и преподаватели готовы.",
                flush=True,
            )
    report = ROOT / ".demo-data" / "expanded-school.json"
    old = {}
    if report.exists():
        try:
            old = json.loads(report.read_text())
        except ValueError:
            old = {}
    state: dict = {"state_version": 2}
    if isinstance(old.get("year_fingerprint"), dict):
        state["year_fingerprint"] = old["year_fingerprint"]
    state["classes"] = summary
    report.parent.mkdir(exist_ok=True)
    report.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def repair_demo_lessons(mapping: list[dict]) -> None:
    """Меняет учителя только у демо-уроков, сохраняя ID и публикуя события."""
    source = (ROOT / "tools" / "repair_demo_lesson_teachers.py").read_text()
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "schedule-api",
            "/app/.venv/bin/python",
            "-c",
            source,
        ],
        cwd=ROOT,
        input=json.dumps(mapping),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise DemoError(
            "Не удалось безопасно изменить преподавателей демо-уроков; изменения уроков откатились."
        )
    outcome = json.loads(result.stdout)
    print(
        f"Исправлено уроков: {outcome['changed']}; пропущено ранее изменённых: {outcome['skipped']}.",
        flush=True,
    )
