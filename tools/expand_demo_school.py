"""Расширяет локальную демо-школу: 1–11 классы А–Д, ученики и расписание.

Запуск: python3 tools/create_demo_data.py --large --apply
Повторно использует демо-учётки и существующие уроки, не удаляет данные.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date, timedelta
from urllib.parse import urlencode

from create_demo_data import ROOT, DemoError, choose_lesson_start, ensure_user

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


def emails(grade: int, code: str, index: int | None = None) -> str:
    prefix = f"{grade:02}" + ("" if code == "a" else f".{code}")
    return (
        f"student{prefix}.{index}@demo.og.test"
        if index
        else f"teacher{prefix}@demo.og.test"
    )


def subject_teacher_email(grade: int, code: str, subject_id: int) -> str:
    """Прежний преподаватель класса остаётся преподавателем математики."""
    if subject_id == 1:
        return emails(grade, code)
    return f"teacher{grade:02}.{code}.subject{subject_id}@demo.og.test"


def expansion_accounts() -> list[dict]:
    accounts = []
    for grade in range(1, 12):
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
            for subject_id, _ in SUBJECTS:
                if subject_id == 1:
                    continue
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


def subject_for(grade: int, day: date, slot: int) -> int:
    """Отдаёт предмет слота из недельной сетки ступени обучения.

    Сетка задаётся явно (WEEKLY_CURRICULUM): количество часов каждого
    предмета правдоподобно для параллели и в сумме ровно заполняет
    учебные дни. Раньше предметы шли по кругу остатков, и при наложении
    нескольких источников у класса собиралось по 5–6 часов одного
    предмета в неделю.
    """
    plan = _grade_day_plan(grade)
    day_row = plan[day.weekday() % len(plan)]
    return day_row[slot % len(day_row)]


# Недельные часы предметов по ступеням. Сумма каждой сетки кратна пяти
# учебным дням: начальная школа — 5 уроков в день, средняя и старшая — 6.
WEEKLY_CURRICULUM: dict[str, dict[int, int]] = {
    "primary": {
        1: 5,  # математика
        2: 5,  # русский язык
        1001: 4,  # литература
        1002: 3,  # окружающий мир
        1004: 3,  # английский язык
        1009: 3,  # физическая культура
        1003: 2,  # история
    },
    "middle": {
        1: 5,
        2: 5,
        1001: 3,
        1003: 3,
        1004: 3,
        1005: 3,
        1007: 3,
        1008: 2,
        1009: 3,
    },
    "senior": {
        1: 5,
        2: 4,
        1001: 3,
        1003: 3,
        1004: 3,
        1005: 2,
        1006: 3,
        1007: 2,
        1008: 2,
        1009: 3,
    },
}

_DAY_PLAN_CACHE: dict[int, list[list[int]]] = {}


def _grade_day_plan(grade: int) -> list[list[int]]:
    """Строит детерминированную сетку «день недели → предметы слотов».

    Часы предмета распределяются по разным дням (сначала по одному
    в день, вторые часы — в наименее заполненные дни), поэтому набор
    предметов каждого учебного дня разнообразен.
    """
    cached = _DAY_PLAN_CACHE.get(grade)
    if cached is not None:
        return cached
    stage = "primary" if grade <= 4 else "middle" if grade <= 6 else "senior"
    weekly = WEEKLY_CURRICULUM[stage]
    days_count = 5
    target = 5 if grade <= 4 else 6
    if sum(weekly.values()) != days_count * target:
        raise ValueError(
            f"Недельная сетка ступени {stage} не заполняет "
            f"{days_count} дней по {target} уроков"
        )
    day_rows: list[list[int]] = [[] for _ in range(days_count)]
    for subject_id, hours in sorted(
        weekly.items(), key=lambda item: (-item[1], item[0])
    ):
        # Часы предмета расходятся по разным дням: сначала в наименее
        # заполненные, поэтому итоговая длина каждого дня одинакова.
        for _ in range(hours):
            options = [
                index for index, row in enumerate(day_rows) if subject_id not in row
            ]
            if not options:
                raise ValueError(
                    f"Сетка ступени {stage}: предмет {subject_id} не помещается "
                    f"по одному уроку в {days_count} дней"
                )
            chosen_day = min(options, key=lambda index: (len(day_rows[index]), index))
            day_rows[chosen_day].append(subject_id)
    for day_index, row in enumerate(day_rows):
        if len(row) != target:
            raise ValueError(
                f"Сетка ступени {stage}: день {day_index} получил {len(row)} "
                f"предметов вместо {target}"
            )
        # Сдвиг чередует порядок предметов между днями и параллелями,
        # чтобы один предмет не открывал каждый день.
        shift = (grade + day_index) % target
        day_rows[day_index] = row[-shift:] + row[:-shift]
    _DAY_PLAN_CACHE[grade] = day_rows
    return day_rows


def apply_expansion(gateway, journal, schedule, days, study_year):
    """Добавляет только отсутствующие демо-данные, сохраняя существующие записи."""
    accounts = expansion_accounts()
    users = {
        u["email"]: u for u in gateway.request("GET", "/internal/backoffice/users")
    }
    for i, account in enumerate(accounts, 1):
        ensure_user(gateway, account, users)
        if i % 100 == 0:
            print(f"Учётные записи: {i}/{len(accounts)}", flush=True)

    subject_config = {
        "subjects": [{"id": id, "name": name} for id, name in SUBJECTS],
        "allowed_teacher_ids": [
            users[subject_teacher_email(g, c, subject_id)]["id"]
            for g in range(1, 12)
            for c in CODES
            for subject_id, _ in SUBJECTS
        ],
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
    teacher_mapping = []
    for grade in range(1, 12):
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
            subject_teachers = {}
            for subject_id, subject_name in SUBJECTS:
                subject_teacher = users[subject_teacher_email(grade, code, subject_id)]
                subject_teachers[subject_id] = subject_teacher
                journal.request(
                    "PUT",
                    f"/internal/teachers/{subject_teacher['id']}/classes/{class_id}",
                    ok=(201, 204),
                )
                teacher_mapping.append(
                    {
                        "class_id": class_id,
                        "subject_id": subject_id,
                        "old_teacher_id": teacher["id"],
                        "teacher_id": subject_teacher["id"],
                    }
                )
            for index in range(1, STUDENTS_PER_CLASS + 1):
                student = users[emails(grade, code, index)]
                journal.request(
                    "PUT",
                    f"/internal/students/{student['id']}/current-class-period",
                    {"class_id": class_id},
                    ok=(200, 201),
                )
            created = 0
            for day in days:
                query = urlencode({"class_id": class_id, "date": day.isoformat()})
                class_lessons = schedule.request("GET", "/lessons?" + query)
                active = [row for row in class_lessons if row["status"] == "planned"]
                target_lessons = 5 if grade <= 4 else 6
                while len(active) < target_lessons:
                    subject_id = subject_for(grade, day, len(active))
                    subject_teacher = subject_teachers[subject_id]
                    subject_teacher_day = schedule.request(
                        "GET",
                        "/internal/teacher-lessons?"
                        + urlencode(
                            {"date_from": day.isoformat(), "date_to": day.isoformat()}
                        ),
                        headers={"X-Teacher-ID": subject_teacher["id"]},
                    )
                    start = choose_lesson_start(
                        day, class_lessons + subject_teacher_day
                    )
                    body = {
                        "class_id": class_id,
                        "teacher_id": subject_teacher["id"],
                        "subject_id": subject_id,
                        "starts_at": start.isoformat(),
                        "ends_at": (start + timedelta(minutes=45)).isoformat(),
                    }
                    key = (
                        "demo-expanded-"
                        + hashlib.sha256(
                            json.dumps(body, sort_keys=True).encode()
                        ).hexdigest()
                    )
                    lesson = schedule.request(
                        "POST",
                        "/lessons",
                        body,
                        ok=(200, 201),
                        headers={"Idempotency-Key": key},
                    )
                    active.append(lesson)
                    class_lessons.append(lesson)
                    created += 1
            summary.append(
                {
                    "name": name,
                    "id": class_id,
                    "teacher": teacher["email"],
                    "subject_teachers": {
                        name: subject_teachers[id]["email"] for id, name in SUBJECTS
                    },
                    "students": [
                        emails(grade, code, i) for i in range(1, STUDENTS_PER_CLASS + 1)
                    ],
                    "lessons_added": created,
                }
            )
            print(
                f"{name}: {STUDENTS_PER_CLASS} учеников, {5 if grade <= 4 else 6} уроков в день; добавлено уроков: {created}.",
                flush=True,
            )
    from rebuild_demo_timetable import TIMETABLE_VERSION, rebuild_timetable

    all_classes = [{"id": row["id"], "name": row["name"]} for row in by_name.values()]
    timetable = rebuild_timetable(journal, days, all_classes, users)

    report = ROOT / ".demo-data" / "expanded-school.json"
    for item in summary:
        item["subject_teachers"] = {}
    report.parent.mkdir(exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "timetable_version": TIMETABLE_VERSION,
                "dates": [str(days[0]), str(days[-1])],
                "timetable": timetable,
                "classes": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
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
