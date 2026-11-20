"""Перестраивает демо-расписание в правдоподобную школьную сетку.

Три шага на основе фактических уроков демо-набора:

1. предметы перераспределяются по дням недели внутри каждого класса,
   чтобы убрать школьные дневные перекосы («65 уроков математики
   в понедельник»), сохранив число уроков класса в каждый день
   и недельный набор предметов класса;
2. каждая пара (класс, предмет) закрепляется за одним предметником
   из небольшого пула, сбалансированно по числу уроков;
3. уроки расставляются по последовательным часам с 9:00 так, чтобы
   учитель никогда не был нужен в двух классах одновременно: на каждый
   час решается паросочетание «класс → свободный преподаватель».

В результате у занятого учителя около 5–6 уроков в день; у проверяемого
учителя математики teacher01@demo.og.test — насыщенная неделя
в нескольких классах.

Уроки с домашними заданиями защищены: им сохраняют предмет, день
и преподавателя; сместиться может только время в пределах дня.

Запуск: python3 tools/create_demo_data.py --large --apply
(вызывается из expand_demo_school.apply_expansion).
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from create_demo_data import ROOT, TIMEZONE, DemoError
from expand_demo_school import CODES, LETTERS, SUBJECTS, emails, subject_teacher_email

LESSON_MINUTES = 45
FIRST_HOUR = 9
TARGET_DAY_LESSONS = 5.0
HARD_DAY_LIMIT = 7
MAX_CLASSES_PER_TEACHER = 8
TEACHER01_EMAIL = "teacher01@demo.og.test"
PRIMARY_GRADES = frozenset(range(1, 5))
PHYSICS_ID = 1006
TIMETABLE_VERSION = 3
DEBUG_POOLS = False


def grade_of(name: str) -> int:
    """Возвращает параллель класса по имени вида «7А»."""
    digits = "".join(ch for ch in name if ch.isdigit())
    if not digits:
        raise DemoError(f"Не удалось определить параллель класса {name}")
    return int(digits)


def stage_of(grade: int) -> str:
    """Делит классы на начальную и основную ступени."""
    return "primary" if grade in PRIMARY_GRADES else "secondary"


def local_day_and_hour(lesson: dict) -> tuple[date, int]:
    """Возвращает локальные дату и час урока во времени школы."""
    starts = datetime.fromisoformat(lesson["starts_at"]).astimezone(TIMEZONE)
    return starts.date(), starts.hour


def email_of(users: dict, user_id: str) -> str | None:
    """Находит демо-email пользователя по UUID."""
    return next((mail for mail, user in users.items() if user["id"] == user_id), None)


def homework_lesson_ids() -> set[int]:
    """Читает номера уроков с ДЗ из локальной базы Homework (только чтение)."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "homework-postgres",
            "psql",
            "-U",
            "homework",
            "-d",
            "homework",
            "-t",
            "-A",
            "-c",
            (
                "select issued_lesson_id from homework_assignments "
                "union select due_lesson_id from homework_assignments "
                "where due_lesson_id is not null"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise DemoError("Не удалось прочитать ссылки ДЗ из локальной базы Homework")
    return {int(row) for row in result.stdout.split() if row.strip()}


def run_db(data):
    """Выполняет скрипт balance_demo_lessons_db внутри контейнера Schedule."""
    source = (ROOT / "tools" / "balance_demo_lessons_db.py").read_text()
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
        input=json.dumps(data),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise DemoError(
            "Не удалось безопасно перестроить демо-расписание; "
            "изменения уроков откатились."
        )
    return json.loads(result.stdout)


def spread(values: list, size: int) -> list:
    """Выбирает size элементов, равномерно распределённых по списку."""
    if size >= len(values):
        return list(values)
    if size <= 0:
        return []
    step = len(values) / size
    picked: list = []
    last = -1
    for index in range(size):
        position = max(round(index * step), last + 1)
        if position >= len(values):
            break
        picked.append(values[position])
        last = position
    return picked


def candidate_emails(subject_id: int, grades: range) -> list[str]:
    """Перечисляет демо-email преподавателей предмета по параллелям."""
    if subject_id == 1:
        return [emails(grade, code) for grade in grades for code in CODES]
    return [
        subject_teacher_email(grade, code, subject_id)
        for grade in grades
        for code in CODES
    ]


def class_teacher_emails() -> set[str]:
    """Перечисляет аккаунты классных руководителей демо-классов."""
    from expand_demo_school import emails as class_email

    return {class_email(grade, code) for grade in range(1, 12) for code in CODES}


# ------------------------------------------------------------------ шаг 1


def plan_day_subjects(
    lessons: list[dict], protected: set[int], days: list[date]
) -> dict[int, dict[date, list[dict]]]:
    """Выравнивает предметы класса по дням каждой недели.

    Защищённые уроки остаются в своём дне; свободные раскладываются
    по свободным слотам дней так, чтобы дневное число уроков предмета
    по школе было максимально ровным. Число уроков класса в день
    и недельный набор предметов класса не меняются.
    """
    global_counts: Counter[tuple[int, date]] = Counter()
    for lesson in lessons:
        day, _hour = local_day_and_hour(lesson)
        global_counts[(lesson["subject_id"], day)] += 1
    weeks: dict[date, list[date]] = {}
    for day in days:
        weeks.setdefault(day - timedelta(days=day.weekday()), []).append(day)
    result: dict[int, dict[date, list[dict]]] = {}
    by_class: dict[int, list[dict]] = defaultdict(list)
    for lesson in lessons:
        by_class[lesson["class_id"]].append(lesson)
    for class_id in sorted(by_class):
        class_lessons = sorted(
            by_class[class_id], key=lambda row: (row["starts_at"], row["id"])
        )
        result[class_id] = {}
        for week_start in sorted(weeks):
            week_days = set(weeks[week_start])
            week_lessons = [
                row for row in class_lessons if local_day_and_hour(row)[0] in week_days
            ]
            if not week_lessons:
                continue
            pinned: dict[date, list[dict]] = defaultdict(list)
            free: list[dict] = []
            for row in week_lessons:
                day, _hour = local_day_and_hour(row)
                if row["id"] in protected:
                    pinned[day].append({**row, "_day": day, "_protected": True})
                else:
                    free.append(row)
            capacity = Counter(local_day_and_hour(row)[0] for row in week_lessons)
            free_slots = {
                day: capacity[day] - len(pinned.get(day, []))
                for day in weeks[week_start]
            }
            week_total = Counter(row["subject_id"] for row in week_lessons)
            free.sort(key=lambda row: (-week_total[row["subject_id"]], row["id"]))
            day_subjects: dict[date, Counter] = defaultdict(Counter)
            for day, rows in pinned.items():
                for row in rows:
                    day_subjects[day][row["subject_id"]] += 1
            for row in free:
                subject = row["subject_id"]
                options = [day for day in weeks[week_start] if free_slots[day] > 0]
                if not options:
                    raise DemoError(f"Нет слота дня для урока {row['id']}")
                chosen = min(
                    options,
                    key=lambda day: (
                        global_counts[(subject, day)],
                        day_subjects[day][subject] > 0,
                        -free_slots[day],
                        day,
                    ),
                )
                free_slots[chosen] -= 1
                global_counts[(subject, chosen)] += 1
                day_subjects[chosen][subject] += 1
                result[class_id].setdefault(chosen, []).append(
                    {**row, "_day": chosen, "_protected": False}
                )
            for day, rows in pinned.items():
                result[class_id].setdefault(day, []).extend(rows)
    return result


# ------------------------------------------------------------------ шаг 2


def partition_teachers(
    by_class_day: dict[int, dict[date, list[dict]]],
    classes: list[dict],
    users: dict,
    pinned: dict[tuple[int, int], str],
    extra_teachers: int = 0,
) -> dict[tuple[int, int], str]:
    """Закрепляет каждый (класс, предмет) за одним предметником пула.

    Пул небольшого размера, чтобы у учителя выходило около
    TARGET_DAY_LESSONS уроков в день; классы раздаются наименее
    загруженным. Защищённые ДЗ-пары остаются у своего преподавателя,
    а teacher01@demo.og.test гарантированно ведёт математику.
    """
    grade_of_class = {c["id"]: grade_of(c["name"]) for c in classes}
    teacher01_id = users.get(TEACHER01_EMAIL, {}).get("id")
    lesson_counts: Counter[tuple[int, int]] = Counter()
    day_counts: dict[tuple[int, int], Counter] = {}
    for class_id, by_day in by_class_day.items():
        for rows in by_day.values():
            for row in rows:
                key = (class_id, row["subject_id"])
                lesson_counts[key] += 1
                day_counts.setdefault(key, Counter())[row["_day"]] += 1
    day_cap = HARD_DAY_LIMIT
    subject_grades = {
        1002: frozenset(range(1, 5)),
        PHYSICS_ID: frozenset(range(7, 12)),
    }
    result: dict[tuple[int, int], str] = {}
    for subject_id, _name in SUBJECTS:
        allowed = subject_grades.get(subject_id)
        keys = sorted(
            key
            for key in lesson_counts
            if key[1] == subject_id
            and (allowed is None or grade_of_class.get(key[0]) in allowed)
        )
        if not keys:
            continue
        grades_range = allowed or frozenset(range(1, 12))
        pool_grades = range(min(grades_range), max(grades_range) + 1)
        base_pool = [
            email
            for email in candidate_emails(subject_id, pool_grades)
            if email in users
        ]
        if subject_id == 1 and TEACHER01_EMAIL in users:
            base_pool = [
                TEACHER01_EMAIL,
                *(email for email in base_pool if email != TEACHER01_EMAIL),
            ]
        pinned_keys = [key for key in keys if key in pinned]
        total = sum(lesson_counts[key] for key in keys)
        pinned_pool = []
        for key in pinned_keys:
            teacher = pinned[key]
            if teacher not in pinned_pool:
                pinned_pool.append(teacher)
        pinned_load = sum(lesson_counts[key] for key in pinned_keys if key in pinned)
        free_total = total - pinned_load
        pinned_emails = {email_of(users, t) for t in pinned_pool}
        pinned_emails.discard(None)
        # Свободные классы достаются только «полноставочным» учителям пула;
        # закреплённые классные руководители остаются при своих классах.
        extra_candidates = [
            email
            for email in base_pool
            if email == TEACHER01_EMAIL or email not in pinned_emails
        ]
        min_size = max(3, round(free_total / (TARGET_DAY_LESSONS * 10)))
        colored = None
        for size in range(min_size, len(extra_candidates) + 1):
            pool = spread(extra_candidates, size)
            free_colors = [users[email]["id"] for email in pool if email in users]
            loads: Counter[str] = Counter()
            classes_of: dict[str, set[int]] = defaultdict(set)
            teacher_days: dict[str, Counter] = defaultdict(Counter)
            assignment: dict[tuple[int, int], str] = {}
            ok = True
            for key in pinned_keys:
                teacher = pinned[key]
                if key[0] in classes_of[teacher]:
                    ok = False
                    break
                assignment[key] = teacher
                loads[teacher] += lesson_counts[key]
                classes_of[teacher].add(key[0])
                for day, count in day_counts[key].items():
                    teacher_days[teacher][day] += count
            if not ok:
                raise DemoError(
                    f"Защищённые преподаватели предмета {subject_id} конфликтуют"
                )
            free_keys = [key for key in keys if key not in assignment]
            free_keys.sort(key=lambda key: (-lesson_counts[key], key[0], key[1]))
            for key in free_keys:
                options = [
                    teacher
                    for teacher in free_colors
                    if key[0] not in classes_of[teacher]
                    and len(classes_of[teacher]) < MAX_CLASSES_PER_TEACHER
                    and all(
                        teacher_days[teacher][day] + count <= day_cap
                        for day, count in day_counts[key].items()
                    )
                ]
                if not options:
                    ok = False
                    break
                teacher = min(
                    options,
                    key=lambda item: (
                        # Проверяемому учителю отдаём классы в первую очередь,
                        # пока его средняя нагрузка не выйдет на полную ставку.
                        0 if item == teacher01_id and loads[item] < 55 else 1,
                        # Равномерность по дням важнее общей нагрузки:
                        # день с 3 и день с 7 хуже, чем два дня по 5.
                        max(teacher_days[item].values(), default=0),
                        loads[item],
                        free_colors.index(item),
                    ),
                )
                assignment[key] = teacher
                loads[teacher] += lesson_counts[key]
                classes_of[teacher].add(key[0])
                for day, count in day_counts[key].items():
                    teacher_days[teacher][day] += count
            if not ok:
                continue
            if DEBUG_POOLS:
                print(
                    f"  [pool] subject={subject_id} extra={len(free_colors)} "
                    f"pinned={len(pinned_pool)} lessons={total} "
                    f"load={sorted(loads.values(), reverse=True)}",
                    flush=True,
                )
            colored = assignment
            break
        if colored is None:
            raise DemoError(
                f"Не удалось распределить предмет {subject_id} по пулу учителей"
            )
        result.update(colored)
    return result


# ------------------------------------------------------------------ шаг 3


def match_period(
    active: list[int],
    remaining: dict[int, list[int]],
    teacher_of: dict[tuple[int, int], str],
    busy: set[tuple[str, int]],
    period: int,
    remaining_periods: int,
) -> dict[int, str] | None:
    """Подбирает классам свободных преподавателей на один час.

    Классу нужен любой из его оставшихся предметов, преподаватель
    которого в этот час ещё не занят. Сначала матчятся критичные
    классы (осталось предметов не меньше, чем часов), а внутри цепи
    предпочитаются преподаватели с самым большим остатком спроса —
    иначе востребованный учитель обнаруживается только к вечеру.
    """
    demand: Counter[str] = Counter()
    for class_id in active:
        for subject in set(remaining[class_id]):
            teacher = teacher_of.get((class_id, subject))
            if teacher:
                demand[teacher] += 1

    match_teacher: dict[str, int] = {}
    match_class: dict[int, str] = {}

    def try_augment(class_id: int, seen: set[str]) -> bool:
        """Увеличивающая цепь Куна для одного класса."""
        candidates = []
        for subject in set(remaining[class_id]):
            teacher = teacher_of.get((class_id, subject))
            if teacher and (teacher, period) not in busy:
                candidates.append(teacher)
        for teacher in sorted(candidates, key=lambda item: (-demand[item], item)):
            if teacher in seen:
                continue
            seen.add(teacher)
            held = match_teacher.get(teacher)
            if held is None or try_augment(held, seen):
                match_teacher[teacher] = class_id
                match_class[class_id] = teacher
                return True
        return False

    critical = [
        class_id for class_id in active if len(remaining[class_id]) >= remaining_periods
    ]
    ordered = [
        *sorted(critical, key=lambda item: (-len(remaining[item]), item)),
        *sorted(
            (item for item in active if item not in set(critical)),
            key=lambda item: (-len(remaining[item]), item),
        ),
    ]
    matched_any = False
    for class_id in ordered:
        if try_augment(class_id, set()):
            matched_any = True
    if not matched_any:
        return None
    return match_class


def assign_periods(
    by_class_day: dict[int, dict[date, list[dict]]],
    teacher_of: dict[tuple[int, int], str],
) -> dict[int, dict[int, dict]]:
    """Расставляет уроки по часам через почасовые паросочетания.

    Каждый час класс получает один предмет из оставшихся, преподаватель
    которого свободен; уроки класса идут подряд с 9:00 без дыр.
    Защищённые уроки занимают слот своего предмета в своём дне.
    """
    placement: dict[int, dict[int, dict]] = defaultdict(dict)
    days = sorted({day for by_day in by_class_day.values() for day in by_day})
    for day in days:
        day_classes = sorted(
            class_id for class_id, by_day in by_class_day.items() if day in by_day
        )
        remaining: dict[int, list[int]] = {}
        for class_id in day_classes:
            remaining[class_id] = sorted(
                row["subject_id"] for row in by_class_day[class_id][day]
            )
        school_left: Counter[int] = Counter()
        for class_id in day_classes:
            school_left.update(remaining[class_id])
        max_len = max((len(rows) for rows in remaining.values()), default=0)
        busy: set[tuple[str, int]] = set()
        chosen: dict[int, dict[int, int]] = {c: {} for c in day_classes}
        period = 0
        while any(remaining.values()):
            period += 1
            if period > max_len + 2:
                raise DemoError(
                    f"Не удалось подобрать преподавателей на {day} к часу {period}"
                )
            active = [c for c in day_classes if remaining[c]]
            matched = match_period(
                active,
                remaining,
                teacher_of,
                busy,
                period,
                remaining_periods=max(1, max_len + 1 - period),
            )
            if matched is None:
                raise DemoError(
                    f"Никого не удалось распределить на {day}, час {period}"
                )
            for class_id, teacher in sorted(matched.items()):
                options = [
                    subject
                    for subject in set(remaining[class_id])
                    if teacher_of.get((class_id, subject)) == teacher
                ]
                # Сначала забираем самый востребованный предмет дня:
                # узким пулам нужны свободные часы, пока они ещё есть.
                subject = min(options, key=lambda s: (-school_left[s], s))
                remaining[class_id].remove(subject)
                school_left[subject] -= 1
                busy.add((teacher, period))
                chosen[class_id][period] = subject
        for class_id in day_classes:
            unused_pinned: dict[int, list[dict]] = defaultdict(list)
            free_lessons: list[dict] = []
            for row in by_class_day[class_id][day]:
                if row["_protected"]:
                    unused_pinned[row["subject_id"]].append(row)
                else:
                    free_lessons.append(row)
            free_lessons.sort(key=lambda row: row["id"])
            for period in sorted(chosen[class_id]):
                subject = chosen[class_id][period]
                if subject is None:
                    continue
                if unused_pinned.get(subject):
                    lesson = unused_pinned[subject].pop(0)
                elif free_lessons:
                    lesson = free_lessons.pop(0)
                else:
                    raise DemoError(
                        f"Нет урока для слота {class_id} {day} час {period}"
                    )
                placement[class_id][lesson["id"]] = {
                    "period": period,
                    "day": day,
                    "subject_id": subject,
                }
            if free_lessons or any(unused_pinned.values()):
                raise DemoError(f"Не все уроки {class_id} на {day} получили час")
    return placement


def conventional_teacher(class_name: str, users: dict) -> str | None:
    """Возвращает классного руководителя демо-класса по имени.

    Математика демо-классов выдаётся классным руководителем:
    у «7А» это teacher07@. Старая балансировка уводила эти пары
    к другим учителям; перестройка возвращает штатного преподавателя.
    """
    digits = "".join(ch for ch in class_name if ch.isdigit())
    letter = "".join(ch for ch in class_name if not ch.isdigit())
    if not digits or letter not in LETTERS:
        return None
    code = CODES[LETTERS.index(letter)]
    email = emails(int(digits), code)
    return users[email]["id"] if email in users else None


# ------------------------------------------------------------------ план


def build_plan(
    lessons: list[dict],
    placement: dict[int, dict[int, dict]],
    teacher_by_key: dict[tuple[int, int], str],
) -> list[dict]:
    """Формирует список фактических изменений уроков."""
    plan = []
    for lesson in lessons:
        target = placement[lesson["class_id"]].get(lesson["id"])
        if target is None:
            continue
        start = datetime.combine(
            target["day"], time(FIRST_HOUR + target["period"] - 1), TIMEZONE
        )
        end = start + timedelta(minutes=LESSON_MINUTES)
        new_teacher = teacher_by_key.get(
            (lesson["class_id"], target["subject_id"]), lesson["teacher_id"]
        )
        unchanged = (
            lesson["subject_id"] == target["subject_id"]
            and lesson["teacher_id"] == new_teacher
            and datetime.fromisoformat(lesson["starts_at"]).astimezone(TIMEZONE)
            == start
        )
        if unchanged:
            continue
        plan.append(
            {
                "id": lesson["id"],
                "before": {
                    key: lesson[key]
                    for key in (
                        "id",
                        "class_id",
                        "teacher_id",
                        "subject_id",
                        "starts_at",
                        "ends_at",
                        "version",
                    )
                },
                "teacher_id": new_teacher,
                "subject_id": target["subject_id"],
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
            }
        )
    return plan


def plan_rebuild(
    lessons: list[dict],
    protected: set[int],
    classes: list[dict],
    users: dict,
) -> tuple[list[dict], dict[tuple[int, int], str], dict]:
    """Собирает план перестройки: изменения уроков и распределение учителей."""
    pinned: dict[tuple[int, int], str] = {}
    reviewers = class_teacher_emails()
    name_by_id = {c["id"]: c["name"] for c in classes}
    for lesson in lessons:
        if lesson["id"] not in protected:
            continue
        key = (lesson["class_id"], lesson["subject_id"])
        # Математика возвращается штатному классному руководителю
        # (teacherNN@ из README демо-набора): так задокументированные
        # проверяющие сохраняют доступ к ДЗ, даже если старая
        # балансировка увела их класс к другому учителю.
        if lesson["subject_id"] == 1:
            conventional = conventional_teacher(
                name_by_id.get(lesson["class_id"], ""), users
            )
            if conventional:
                if pinned.get(key, conventional) != conventional:
                    raise DemoError("У класса конфликт штатных преподавателей предмета")
                pinned[key] = conventional
                continue
        email = email_of(users, lesson["teacher_id"])
        if email not in reviewers:
            continue
        if pinned.get(key, lesson["teacher_id"]) != lesson["teacher_id"]:
            raise DemoError(
                "У защищённых ДЗ-уроков одного предмета разные преподаватели"
            )
        pinned[key] = lesson["teacher_id"]
    days = sorted({local_day_and_hour(row)[0] for row in lessons})
    by_class_day = plan_day_subjects(lessons, protected, days)
    teacher_by_key = None
    placement = None
    for boost in range(4):
        candidate_teachers = partition_teachers(
            by_class_day, classes, users, pinned, extra_teachers=boost
        )
        try:
            placement = assign_periods(by_class_day, candidate_teachers)
        except DemoError:
            if boost == 3:
                raise
            continue
        teacher_by_key = candidate_teachers
        break
    assert teacher_by_key is not None and placement is not None
    plan = build_plan(lessons, placement, teacher_by_key)
    stats = summarize(lessons, placement, teacher_by_key, users)
    return plan, teacher_by_key, stats


def summarize(
    lessons: list[dict],
    placement: dict[int, dict[int, dict]],
    teacher_by_key: dict[tuple[int, int], str],
    users: dict,
) -> dict:
    """Считает сводку нагрузок для отчёта и контроля результата."""
    day_counts: Counter[tuple[str, str]] = Counter()
    subjects_by_teacher: dict[str, set[int]] = defaultdict(set)
    for (class_id, subject_id), teacher in teacher_by_key.items():
        subjects_by_teacher[teacher].add(subject_id)
        for row in placement[class_id].values():
            if row["subject_id"] == subject_id:
                day_counts[(email_of(users, teacher) or "?", str(row["day"]))] += 1
    return {
        "teacher_day_distribution": dict(sorted(Counter(day_counts.values()).items())),
        "teacher01_days": {
            day: count
            for (email, day), count in sorted(day_counts.items())
            if email == TEACHER01_EMAIL
        },
        "teachers": len(subjects_by_teacher),
    }


# ------------------------------------------------------------------ проверки


def verify_state(lessons: list[dict], users: dict) -> tuple[bool, dict]:
    """Проверяет фактическое расписание и возвращает сводку."""
    teacher_by_key: dict[tuple[int, int], str] = {}
    for lesson in lessons:
        key = (lesson["class_id"], lesson["subject_id"])
        if key in teacher_by_key and teacher_by_key[key] != lesson["teacher_id"]:
            return False, {"reason": "предмет класса ведут разные учителя"}
        teacher_by_key[key] = lesson["teacher_id"]
    subjects_by_teacher: dict[str, set[int]] = defaultdict(set)
    day_counts: Counter[tuple[str, str]] = Counter()
    teacher_busy: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    class_busy: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    for lesson in lessons:
        start = datetime.fromisoformat(lesson["starts_at"])
        end = datetime.fromisoformat(lesson["ends_at"])
        for begin, finish in teacher_busy[lesson["teacher_id"]]:
            if start < finish and begin < end:
                return False, {"reason": "пересечение уроков учителя"}
        teacher_busy[lesson["teacher_id"]].append((start, end))
        for begin, finish in class_busy[lesson["class_id"]]:
            if start < finish and begin < end:
                return False, {"reason": "пересечение уроков класса"}
        class_busy[lesson["class_id"]].append((start, end))
        subjects_by_teacher[lesson["teacher_id"]].add(lesson["subject_id"])
        day_counts[
            (
                email_of(users, lesson["teacher_id"]) or "?",
                str(start.astimezone(TIMEZONE).date()),
            )
        ] += 1
    multi = sorted(
        {
            email_of(users, teacher) or "?"
            for teacher, rows in subjects_by_teacher.items()
            if len(rows) > 1
        }
    )
    teacher01 = [
        count for (email, _day), count in day_counts.items() if email == TEACHER01_EMAIL
    ]
    distribution = Counter(day_counts.values())
    total_days = max(sum(distribution.values()), 1)
    share_busy = (
        sum(mass for load, mass in distribution.items() if load >= 4) / total_days
    )
    share_spare = distribution.get(1, 0) / total_days
    healthy = (
        not multi
        and len(teacher01) >= 8
        and sum(teacher01) / len(teacher01) >= 4.5
        and max(teacher01, default=0) <= HARD_DAY_LIMIT
        and share_busy >= 0.5
        and share_spare <= 0.15
    )
    return healthy, {
        "teacher_day_distribution": dict(sorted(distribution.items())),
        "teacher01_days": {
            day: count
            for (email, day), count in sorted(day_counts.items())
            if email == TEACHER01_EMAIL
        },
        "teachers_with_lessons": len(subjects_by_teacher),
        "classes": len({row["class_id"] for row in lessons}),
        "multi_subject_teachers": multi,
        "busy_share": round(share_busy, 3),
        "single_lesson_share": round(share_spare, 3),
    }


# ------------------------------------------------------------------ применение


def sync_assignments(
    journal, users: dict, classes: list[dict], needed: set[tuple[str, int]]
) -> None:
    """Синхронизирует назначения Journal с новым расписанием.

    Преподавателям пула выдаются их классы; назначения предметников,
    которые больше ничего не ведут, снимаются. Классные руководители
    и учителя прошлых (октябрьских) уроков сохраняются.
    """
    teaching = run_db({"mode": "teacher_usage", "class_ids": []})
    for teacher, class_id in sorted(needed):
        journal.request(
            "PUT",
            f"/internal/teachers/{teacher}/classes/{class_id}",
            ok=(201, 204),
        )
    removed = 0
    subject_accounts = sorted(
        email
        for email in users
        if ".subject" in email and email.endswith("@demo.og.test")
    )
    for email in subject_accounts:
        user = users[email]
        if teaching.get(user["id"], 0) > 0:
            continue
        current = journal.request("GET", f"/internal/teachers/{user['id']}/classes")
        keep = {class_id for teacher, class_id in needed if teacher == user["id"]}
        for row in current:
            if row["id"] in keep:
                continue
            journal.request(
                "DELETE",
                f"/internal/teachers/{user['id']}/classes/{row['id']}",
                ok=(204,),
            )
            removed += 1
    print(
        f"Назначения Journal: добавлено {len(needed)}, "
        f"снято неиспользуемых предметников: {removed}.",
        flush=True,
    )


def set_subject_allowance(users: dict) -> None:
    """Разрешает демо-предметам всех демо-преподавателей."""
    allowed = [
        user["id"]
        for email, user in sorted(users.items())
        if email.startswith("teacher") and email.endswith("@demo.og.test")
    ]
    if not 1 <= len(allowed) <= 1000:
        raise DemoError("Недопустимое число демо-преподавателей для настроек")
    config = {
        "subjects": [{"id": id, "name": name} for id, name in SUBJECTS],
        "allowed_teacher_ids": allowed,
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
        input=json.dumps(config),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise DemoError("Не удалось подтвердить названия демо-предметов")


def rebuild_timetable(journal, days: list[date], classes: list[dict], users: dict):
    """Перестраивает расписание, если фактическое состояние не проходит проверки."""
    report = ROOT / ".demo-data" / "expanded-school.json"
    old = json.loads(report.read_text()) if report.exists() else {}
    start = datetime.combine(days[0], time.min, TIMEZONE)
    end = datetime.combine(days[-1] + timedelta(days=1), time.min, TIMEZONE)
    teacher_ids = sorted(
        {
            user["id"]
            for email, user in users.items()
            if email.startswith("teacher") and email.endswith("@demo.og.test")
        }
    )
    export = run_db(
        {
            "mode": "export",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "class_ids": sorted({c["id"] for c in classes}),
            "teacher_ids": teacher_ids,
        }
    )
    if any(not row["managed"] for row in export):
        raise DemoError(
            "В демо-классах есть уроки вне демо-скриптов; "
            "автоматическая перестройка небезопасна"
        )
    lessons = list(export)
    healthy, stats = verify_state(lessons, users)
    fingerprint_ok = old.get("timetable_version") == TIMETABLE_VERSION and old.get(
        "dates"
    ) == [str(days[0]), str(days[-1])]
    if fingerprint_ok and healthy:
        print(
            "Расписание уже перестроено и проходит проверки; изменения не нужны.",
            flush=True,
        )
        return stats
    protected = homework_lesson_ids()
    plan, teacher_by_key, plan_stats = plan_rebuild(lessons, protected, classes, users)
    needed = {(teacher, class_id) for (class_id, _s), teacher in teacher_by_key.items()}
    outcome = run_db({"mode": "apply", "plan": plan}) if plan else {"changed": 0}
    sync_assignments(journal, users, classes, needed)
    set_subject_allowance(users)
    print(
        f"Перестроено уроков: {outcome['changed']}. "
        f"Нагрузка учитель-день: {plan_stats['teacher_day_distribution']}. "
        f"teacher01 по дням: {plan_stats['teacher01_days']}.",
        flush=True,
    )
    return plan_stats
