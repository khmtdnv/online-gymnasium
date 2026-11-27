"""Demo timetable tooling: the study-year scenario and the repair path.

The year scenario (rebuild_year) rebuilds the whole study year of the
demo school from scratch, driven by the year fingerprint:

1. the demo homework scenarios are wiped first (the Homework
   container path of tools/balance_homework_scenarios_db.py);
2. every lesson of the demo classes plus their idempotency keys and
   Redis day-cache keys goes in one Schedule-container transaction
   (the wipe mode of tools/balance_demo_lessons_db.py);
3. the emptiness is confirmed by an export that must see no lesson of
   the demo classes;
4. the deterministic year plan (tools/demo_year_plan.build_year_plan
   over tools/demo_curriculum and the school calendar) is inserted in
   class-week chunks (the create mode of balance_demo_lessons_db.py);
5. verify_state checks the hard invariants over the whole year.

A matching fingerprint ({grid_version, calendar_version,
curriculum_hash, study_year}, stored in .demo-data/expanded-school.json)
keeps the lessons untouched (the empty run) - only the homework
scenarios are wiped and recreated afterwards by create_demo_data.

The week repair path (plan_rebuild and friends) stays for live public
data: it reshuffles exported lessons in place through the run_db apply
mode and refuses to touch unmanaged lessons.

Grid boundaries live in schedule_service.domain.school_periods (the
module has no dependencies outside the standard library); the study
year dates come from schedule_service.domain.school_calendar exactly
the same way.

Run: python3 tools/create_demo_data.py --large --apply
(the year scenario is orchestrated from create_demo_data).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path

from create_demo_data import ROOT, DemoError
from demo_curriculum import (
    DAILY_LESSON_LIMIT,
    GRADE_CURRICULUM,
    SCHOOL_DAYS_PER_WEEK,
    SUBJECT_GRADES,
    TRUNCATION_PRIORITY,
)
from demo_year_plan import build_year_plan, place_day_blocks
from expand_demo_school import CODES, LETTERS, SUBJECTS, emails, subject_teacher_email

# Сетка периодов — единственный источник школьного времени; локальных
# копий границ в инструменте нет.
SCHEDULE_SRC = str(Path(ROOT) / "services" / "schedule" / "src")
if SCHEDULE_SRC not in sys.path:
    sys.path.insert(0, SCHEDULE_SRC)

from schedule_service.domain import school_calendar
from schedule_service.domain.school_periods import (
    PERIODS,
    TIMEZONE,
    period_for,
)

TARGET_DAY_LESSONS = 5.0
# Уроков в дне не больше, чем периодов в сетке.
HARD_DAY_LIMIT = len(PERIODS)
MAX_CLASSES_PER_TEACHER = 8
TEACHER01_EMAIL = "teacher01@demo.og.test"
PRIMARY_GRADES = frozenset(range(1, 5))
PHYSICS_ID = 1006
DEBUG_POOLS = False

# Manual version of the demo grid: bump it by hand whenever the teacher
# pool composition or the expand logic changes (new pool lines, another
# account naming, a changed matching policy), so every consumer rebuilds
# the study year from scratch. Curriculum and calendar changes are
# covered by curriculum_hash and calendar_version below instead.
GRID_VERSION = 1

# Location of the year fingerprint and the school composition state.
EXPANDED_SCHOOL_REPORT = ROOT / ".demo-data" / "expanded-school.json"


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


def run_homework_db(data):
    """Runs balance_homework_scenarios_db inside the homework container."""
    source = (ROOT / "tools" / "balance_homework_scenarios_db.py").read_text()
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "homework-api",
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
            "Не удалось очистить демо-сценарии домашних заданий; уроки не тронуты."
        )
    return json.loads(result.stdout)


# ------------------------------------------------------------------
# Year fingerprint (spec section 6)


def curriculum_hash() -> str:
    """Returns sha256 of the canonical JSON of the curriculum tables.

    The canonical form is json.dumps(..., sort_keys=True,
    separators=(",", ":")) over the four tables of
    tools/demo_curriculum.py; any edit of the hours, the subject
    applicability, the daily limits or the truncation order changes
    the hash and forces a full year rebuild.
    """
    payload = {
        "grade_curriculum": GRADE_CURRICULUM,
        "subject_grades": SUBJECT_GRADES,
        "daily_lesson_limit": DAILY_LESSON_LIMIT,
        "truncation_priority": list(TRUNCATION_PRIORITY),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def study_year_label() -> str:
    """Returns the study year label like "2026/27" from the calendar."""
    start, end = school_calendar.STUDY_YEAR
    return f"{start.year}/{end.year % 100:02d}"


def year_fingerprint() -> dict:
    """Builds the canonical year fingerprint of the current sources."""
    return {
        "grid_version": GRID_VERSION,
        "calendar_version": school_calendar.CALENDAR_VERSION,
        "curriculum_hash": curriculum_hash(),
        "study_year": study_year_label(),
    }


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


def _flow_saturates(
    supplies: dict[int, int],
    edge_left: dict[tuple[int, date], int],
    day_free: dict[date, int],
    days: list[date],
) -> bool:
    """Проверяет потоком, что остаток уроков ещё размещается по дням.

    Маленький граф «источник → предметы → дни → сток»; насыщающий поток
    существует только если никакой предмет больше не загнан в тупик.
    """
    subjects = sorted(supplies)
    capacity: dict[tuple[object, object], int] = {}
    for subject in subjects:
        capacity[("src", ("subj", subject))] = supplies[subject]
        for day in days:
            left = edge_left[(subject, day)]
            if left > 0:
                capacity[(("subj", subject), ("day", day))] = left
    for day in days:
        if day_free[day] > 0:
            capacity[(("day", day), "dst")] = day_free[day]
    # остаточная сеть: обратные рёбра нужны, чтобы поток мог
    # перестраивать уже найденные пути — иначе это не максимальный поток
    neighbours: dict[object, list[object]] = defaultdict(list)
    for left, right in capacity:
        neighbours[left].append(right)
        neighbours[right].append(left)
    total = sum(supplies.values())
    flow = 0
    while True:
        # кратчайший увеличивающий путь (BFS)
        parent: dict[object, object] = {}
        queue = ["src"]
        seen = {"src"}
        while queue:
            node = queue.pop(0)
            for next_node in neighbours[node]:
                if next_node not in seen and capacity.get((node, next_node), 0) > 0:
                    seen.add(next_node)
                    parent[next_node] = node
                    queue.append(next_node)
        if "dst" not in parent:
            break
        # узкое место вдоль пути
        bottleneck = None
        node = "dst"
        while node != "src":
            prev = parent[node]
            edge = capacity[(prev, node)]
            bottleneck = edge if bottleneck is None else min(bottleneck, edge)
            node = prev
        node = "dst"
        while node != "src":
            prev = parent[node]
            capacity[(prev, node)] -= bottleneck
            capacity[(node, prev)] = capacity.get((node, prev), 0) + bottleneck
            node = prev
        flow += bottleneck
    return flow == total


def plan_subject_days(
    free_by_subject: dict[int, list[dict]],
    day_limit_of: dict[int, int],
    day_subjects: dict[date, Counter],
    free_slots: dict[date, int],
    global_counts: Counter,
    class_id: int,
    week_start: date,
) -> dict[int, Counter]:
    """Раскладывает свободные уроки предмета по дням с гарантией завершения.

    Каждый шаг — жадный выбор дня (разные дни раньше повторов, меньше
    нагрузка предмета по школе), проверяемый маленьким потоком: если
    выбор загоняет остаток недели в тупик, берётся следующий день.
    """
    days = sorted(free_slots)
    supplies = {subject: len(rows) for subject, rows in free_by_subject.items()}
    edge_left = {
        (subject, day): max(0, day_limit_of[subject] - day_subjects[day][subject])
        for subject in free_by_subject
        for day in days
    }
    day_free = {day: free_slots[day] for day in days}
    targets: dict[int, Counter] = {subject: Counter() for subject in free_by_subject}
    for subject in sorted(free_by_subject, key=lambda item: (supplies[item], item)):
        for row in sorted(free_by_subject[subject], key=lambda item: item["id"]):
            candidates = [
                day
                for day in days
                if edge_left[(subject, day)] > 0 and day_free[day] > 0
            ]
            candidates.sort(
                key=lambda day: (
                    targets[subject][day] > 0,
                    global_counts[(subject, day)],
                    -day_free[day],
                    day,
                )
            )
            placed_day = None
            for day in candidates:
                edge_left[(subject, day)] -= 1
                day_free[day] -= 1
                supplies[subject] -= 1
                if _flow_saturates(supplies, edge_left, day_free, days):
                    placed_day = day
                    break
                edge_left[(subject, day)] += 1
                day_free[day] += 1
                supplies[subject] += 1
            if placed_day is None:
                raise DemoError(
                    "Недельный план класса не собирается: "
                    f"класс {class_id}, предмет {subject}, урок {row['id']}, "
                    f"неделя с {week_start}; свободные дни и лимит "
                    "двух уроков предмета в день исчерпаны"
                )
            targets[subject][placed_day] += 1
    return targets


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
            # Защищённые ДЗ-уроки не должны сами нарушать лимит «не больше
            # двух уроков предмета в день»: иначе неделю нельзя собрать
            # без переноса чужих данных, и это нужно показать явно.
            for day, counts in sorted(day_subjects.items()):
                for subject, count in sorted(counts.items()):
                    if count > 2:
                        ids = sorted(
                            row["id"]
                            for row in pinned[day]
                            if row["subject_id"] == subject
                        )
                        raise DemoError(
                            "Защищённые ДЗ-уроки нарушают лимит дня: "
                            f"класс {class_id}, неделя с {week_start}, "
                            f"предмет {subject}, уроки {ids} все в {day}"
                        )
            # Сколько учебных дней у класса в этой неделе: дубль предмета
            # в дне необходим только если недельных уроков больше, чем дней.
            week_days_count = len(
                [day for day in weeks[week_start] if capacity[day] > 0]
            )
            # Сначала план дней для каждого предмета: по одному уроку
            # в разные дни, второй урок дня — только когда недельное число
            # не помещается по одному (6 уроков за 5 дней → один день
            # с двумя, но не три и не два двойных).
            free_by_subject: dict[int, list[dict]] = defaultdict(list)
            for row in free:
                free_by_subject[row["subject_id"]].append(row)
            # дубль нужен по недельному итогу предмета, включая
            # защищённые уроки: 6 уроков за 5 дней — один дубль,
            # даже если один из шести закреплён за своим днём
            day_limit_of = {
                subject: 2 if week_total[subject] > week_days_count else 1
                for subject in free_by_subject
            }
            day_targets = plan_subject_days(
                free_by_subject,
                day_limit_of,
                day_subjects,
                free_slots,
                global_counts,
                class_id,
                week_start,
            )
            for subject in sorted(day_targets):
                targets = day_targets[subject]
                for row in free_by_subject[subject]:
                    chosen = min(
                        (day for day in targets if targets[day] > 0),
                        key=lambda day: (global_counts[(subject, day)], day),
                    )
                    targets[chosen] -= 1
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
    # Учитель физически не может провести больше уроков, чем часов
    # в самом длинном дне класса: иначе одному его классу гарантировано
    # окно. Дополнительный час запаса не спасает: классы начинаются
    # с первого часа.
    day_cap = max(
        (len(rows) for by_day in by_class_day.values() for rows in by_day.values()),
        default=HARD_DAY_LIMIT,
    )
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
        # extra_teachers расширяет пул предметников: меньше классов
        # на учителя — реже все преподаватели класса заняты один час
        min_size = max(
            3, round(free_total / (TARGET_DAY_LESSONS * 10)) + extra_teachers
        )
        colored = None
        # расширенный пул не может превышать число доступных учителей
        for size in range(
            min(min_size, len(extra_candidates)), len(extra_candidates) + 1
        ):
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


# Подбор периодов внутри непрерывного блока дня (паросочетание
# «урок → период» с занятостью преподавателей и разводкой дублей)
# выделен в tools/demo_year_plan.py и используется здесь и генератором
# года одинаково: match_block, separate_adjacent_duplicates и их
# обёртка place_day_blocks.


def assign_periods(
    by_class_day: dict[int, dict[date, list[dict]]],
    teacher_of: dict[tuple[int, int], str],
) -> dict[int, dict[int, dict]]:
    """Расставляет уроки по периодам сетки непрерывными блоками дней классов.

    День класса занимает один связный интервал периодов семипериодной
    сетки; начало подбирается перебором, поэтому у учеников нет окон при
    любых задержках. Внутри блока предметы распределяются паросочетанием
    с учётом занятости преподавателей, а одинаковые предметы разводятся
    по периодам.
    """
    placement: dict[int, dict[int, dict]] = defaultdict(dict)
    days = sorted({day for by_day in by_class_day.values() for day in by_day})
    for day in days:
        day_classes = sorted(
            class_id for class_id, by_day in by_class_day.items() if day in by_day
        )
        # Защищённые ДЗ-уроки разбираются первыми, порядок строк
        # сохраняется — выделенное паросочетание работает с теми же
        # данными, что и прежний внутренний цикл.
        rows_by_class = {
            class_id: sorted(
                by_class_day[class_id][day],
                key=lambda row: (not row["_protected"], row["id"]),
            )
            for class_id in day_classes
        }
        busy: dict[str, set[int]] = defaultdict(set)
        try:
            periods_of = place_day_blocks(rows_by_class, teacher_of, busy, len(PERIODS))
        except ValueError as error:
            raise DemoError(str(error)) from error
        chosen: dict[int, dict[int, int]] = {c: {} for c in day_classes}
        for class_id in day_classes:
            rows = rows_by_class[class_id]
            for index, period in periods_of[class_id].items():
                chosen[class_id][period] = rows[index]["subject_id"]
        for class_id in day_classes:
            used = sorted(chosen[class_id])
            if used != list(range(used[0], used[0] + len(used))):
                raise DemoError(
                    f"Окно в расписании класса {class_id} на {day}: "
                    f"уроки пришлись на периоды {used}"
                )
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
                        f"Нет урока для слота {class_id} {day} период {period}"
                    )
                placement[class_id][lesson["id"]] = {
                    "period": period,
                    "day": day,
                    "subject_id": subject,
                }
            if free_lessons or any(unused_pinned.values()):
                raise DemoError(f"Не все уроки {class_id} на {day} получили период")
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
    """Формирует список фактических изменений уроков.

    Начало и конец урока — точные границы периода из PERIODS в местном
    времени школы; номер периода один и всегда в пределах сетки.
    """
    plan = []
    for lesson in lessons:
        target = placement[lesson["class_id"]].get(lesson["id"])
        if target is None:
            continue
        period = PERIODS[target["period"] - 1]
        start = datetime.combine(target["day"], period.start_at, TIMEZONE)
        end = datetime.combine(target["day"], period.end_at, TIMEZONE)
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
    for boost in (0, 2, 5, 10, 20):
        candidate_teachers = partition_teachers(
            by_class_day, classes, users, pinned, extra_teachers=boost
        )
        try:
            placement = assign_periods(by_class_day, candidate_teachers)
        except DemoError:
            continue
        teacher_by_key = candidate_teachers
        break
    if teacher_by_key is None or placement is None:
        raise DemoError(
            "Не удалось расставить часы даже с расширенными пулами "
            "преподавателей; проверьте нагрузку демо-школы"
        )
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
    day_subjects: dict[tuple[int, date], Counter] = defaultdict(Counter)
    for class_id, rows in placement.items():
        for row in rows.values():
            day_subjects[(class_id, row["day"])][row["subject_id"]] += 1
    for (class_id, subject_id), teacher in teacher_by_key.items():
        subjects_by_teacher[teacher].add(subject_id)
        for row in placement[class_id].values():
            if row["subject_id"] == subject_id:
                day_counts[(email_of(users, teacher) or "?", str(row["day"]))] += 1
    worst_repeat = max(
        (count for counts in day_subjects.values() for count in counts.values()),
        default=1,
    )
    forced_doubles = sum(
        1 for counts in day_subjects.values() for count in counts.values() if count == 2
    )
    return {
        "teacher_day_distribution": dict(sorted(Counter(day_counts.values()).items())),
        "teacher01_days": {
            day: count
            for (email, day), count in sorted(day_counts.items())
            if email == TEACHER01_EMAIL
        },
        "teachers": len(subjects_by_teacher),
        "max_same_subject_per_day": worst_repeat,
        "forced_doubles": forced_doubles,
    }


# ------------------------------------------------------------------ проверки


def verify_state(
    lessons: list[dict],
    users: dict,
    classes: list[dict] | None = None,
    calendar=None,
) -> tuple[bool, dict]:
    """Verifies the actual timetable against the calendar and the curriculum.

    Hard requirements: no teacher and no class has two lessons at once
    (one linear pass over the time-sorted lessons of every teacher and
    class - O(n) instead of pairwise comparison), every (class, subject)
    pair is taught by exactly one teacher, a class meets one subject at
    most twice a day (the double is allowed only when the school days of
    the study week from the calendar cannot host the weekly hours one
    lesson per day), every lesson matches exactly one of the seven
    periods and class days have no windows.

    Calendar checks: no lesson falls on a vacation or public holiday
    day; with the class list the Saturdays of the five-day primary
    school (grades 1-4) must stay empty and the daily lesson limits of
    tools/demo_curriculum.py must hold. Short study weeks (public
    holidays, quarter boundaries) are the expected norm of the calendar,
    not an anomaly: the weekly expectations always come from the school
    calendar, never from "five days" assumptions.

    Args:
        lessons: exported lesson rows (id, class_id, teacher_id,
            subject_id, starts_at, ends_at, version).
        users: demo email -> account dict with ids (for the summary).
        classes: optional [{id, name}] rows; enable the grade-aware
            checks (empty Saturdays of grades 1-4, daily limits).
        calendar: study-year calendar exposing school_days() and
            is_school_day(); defaults to the schedule domain module.

    Returns:
        (healthy, summary): healthy is False only for the hard
        violations above (the summary then carries the "reason" key);
        the aggregate numbers are informational.
    """
    if calendar is None:
        calendar = school_calendar
    grade_of_class: dict[int, int] = {}
    week_length: dict[int, int] = {}
    if classes:
        grade_of_class = {int(row["id"]): grade_of(row["name"]) for row in classes}
        week_length = {
            class_id: SCHOOL_DAYS_PER_WEEK[grade]
            for class_id, grade in grade_of_class.items()
        }
    week_school_days: dict[date, list[date]] = {}
    for day in calendar.school_days():
        monday = day - timedelta(days=day.weekday())
        week_school_days.setdefault(monday, []).append(day)

    def expected_week_days(class_id: int, monday: date) -> list[date]:
        """School days of the study week the class can use."""
        length = week_length.get(class_id)
        if length is None:
            return week_school_days.get(monday, [])
        return [
            day for day in week_school_days.get(monday, []) if day.weekday() < length
        ]

    teacher_by_key: dict[tuple[int, int], str] = {}
    for lesson in lessons:
        key = (lesson["class_id"], lesson["subject_id"])
        if key in teacher_by_key and teacher_by_key[key] != lesson["teacher_id"]:
            return False, {"reason": "предмет класса ведут разные учителя"}
        teacher_by_key[key] = lesson["teacher_id"]
    subjects_by_teacher: dict[str, set[int]] = defaultdict(set)
    day_counts: Counter[tuple[str, str]] = Counter()
    by_teacher: dict[str, list[tuple[datetime, datetime, dict]]] = defaultdict(list)
    by_class: dict[int, list[tuple[datetime, datetime, dict]]] = defaultdict(list)
    week_subjects: dict[tuple[int, date], Counter] = defaultdict(Counter)
    day_subjects: dict[tuple[int, date], Counter] = defaultdict(Counter)
    class_day_periods: dict[tuple[int, date], list[int]] = defaultdict(list)
    teacher_day_periods: dict[tuple[str, date], list[int]] = defaultdict(list)
    offgrid: list[dict] = []
    for lesson in lessons:
        start = datetime.fromisoformat(lesson["starts_at"])
        end = datetime.fromisoformat(lesson["ends_at"])
        by_teacher[lesson["teacher_id"]].append((start, end, lesson))
        by_class[lesson["class_id"]].append((start, end, lesson))
        subjects_by_teacher[lesson["teacher_id"]].add(lesson["subject_id"])
        local = start.astimezone(TIMEZONE)
        day = local.date()
        week_start = day - timedelta(days=day.weekday())
        week_subjects[(lesson["class_id"], week_start)][lesson["subject_id"]] += 1
        day_subjects[(lesson["class_id"], day)][lesson["subject_id"]] += 1
        day_counts[
            (
                email_of(users, lesson["teacher_id"]) or "?",
                str(day),
            )
        ] += 1
        # Занятость по периодам сетки: вне-сеточный урок не имеет номера
        # периода и ниже бракует состояние целиком.
        period = period_for(start, end)
        if period is not None:
            class_day_periods[(lesson["class_id"], day)].append(period.number)
            teacher_day_periods[(lesson["teacher_id"], day)].append(period.number)
        else:
            offgrid.append({"id": lesson["id"], "day": str(day)})

    # Перекрытия — линейный проход по отсортированным урокам каждого
    # учителя и класса: соседняя пара достаточно, попарно не сравниваем.
    for teacher, rows in by_teacher.items():
        rows.sort(key=lambda row: (row[0], row[1]))
        for (_s1, e1, _r1), (s2, _e2, _r2) in pairwise(rows):
            if s2 < e1:
                return False, {"reason": "пересечение уроков учителя"}
    for class_id, rows in by_class.items():
        rows.sort(key=lambda row: (row[0], row[1]))
        for (_s1, e1, _r1), (s2, _e2, _r2) in pairwise(rows):
            if s2 < e1:
                return False, {"reason": "пересечение уроков класса"}

    forced_doubles = 0
    worst_repeat = (1, None)
    for (class_id, day), counts in sorted(day_subjects.items()):
        week_start = day - timedelta(days=day.weekday())
        expected = expected_week_days(class_id, week_start)
        for subject, count in sorted(counts.items()):
            if count > worst_repeat[0]:
                worst_repeat = (
                    count,
                    f"класс {class_id}, {day}, предмет {subject}",
                )
            if count >= 3:
                return False, {
                    "reason": (
                        f"три и больше уроков предмета {subject} у класса "
                        f"{class_id} в {day}"
                    )
                }
            if count == 2:
                week_total = week_subjects[(class_id, week_start)][subject]
                if week_total <= len(expected):
                    return False, {
                        "reason": (
                            f"двойной урок предмета {subject} у класса "
                            f"{class_id} в {day} не был необходим: за неделю "
                            f"{week_total} уроков на "
                            f"{len(expected)} учебных дней"
                        )
                    }
                forced_doubles += 1
    # Урок вне сетки — само по себе нарушение: после включения контракта
    # периодов демо-расписание обязано лежать на сетке целиком.
    if offgrid:
        return False, {
            "reason": (
                f"вне сетки периодов {len(offgrid)} уроков, например "
                f"{offgrid[0]['id']} ({offgrid[0]['day']})"
            ),
            "offgrid_lessons": offgrid,
        }
    for (class_id, day), used in sorted(class_day_periods.items()):
        ordered = sorted(used)
        if ordered != list(range(ordered[0], ordered[0] + len(ordered))):
            return False, {"reason": f"окно в расписании класса {class_id} на {day}"}
    # Календарные проверки: каникулы и праздники пусты, суббота 1–4
    # пуста, дневные лимиты таблицы часов соблюдены.
    for class_id, day in sorted(class_day_periods):
        if not calendar.is_school_day(day):
            return False, {
                "reason": (
                    f"урок класса {class_id} в неучебный день {day} "
                    "(каникулы или праздник)"
                )
            }
        grade = grade_of_class.get(class_id)
        if grade is not None:
            if day.weekday() == 5 and grade in PRIMARY_GRADES:
                return False, {
                    "reason": (
                        f"урок класса {class_id} в субботу: начальная школа "
                        "учится пять дней"
                    )
                }
            if len(class_day_periods[(class_id, day)]) > DAILY_LESSON_LIMIT[grade]:
                return False, {
                    "reason": (
                        f"класс {class_id} в {day} превышает дневной лимит "
                        f"{DAILY_LESSON_LIMIT[grade]} уроков"
                    )
                }
    teacher_windows: dict[str, int] = Counter()
    worst_teacher_windows: dict[str, dict[str, int]] = defaultdict(dict)
    for (teacher, day), used in sorted(teacher_day_periods.items()):
        ordered = sorted(used)
        windows = len(range(ordered[0], ordered[-1] + 1)) - len(ordered)
        if windows:
            email = email_of(users, teacher) or "?"
            teacher_windows[email] += windows
            worst_teacher_windows[email][str(day)] = windows
    worst_window_entry = None
    if teacher_windows:
        worst_email = max(teacher_windows, key=lambda item: teacher_windows[item])
        worst_window_entry = {
            "teacher": worst_email,
            "total_windows": teacher_windows[worst_email],
            "days": worst_teacher_windows[worst_email],
        }
    multi = sorted(
        {
            email_of(users, teacher) or "?"
            for teacher, rows in subjects_by_teacher.items()
            if len(rows) > 1
        }
    )
    teacher01_days = {
        day: count
        for (email, day), count in sorted(day_counts.items())
        if email == TEACHER01_EMAIL
    }
    distribution = Counter(day_counts.values())
    total_days = max(sum(distribution.values()), 1)
    share_busy = (
        sum(mass for load, mass in distribution.items() if load >= 4) / total_days
    )
    share_spare = distribution.get(1, 0) / total_days
    return True, {
        "teacher_day_distribution": dict(sorted(distribution.items())),
        "teacher01_days": teacher01_days,
        "teachers_with_lessons": len(subjects_by_teacher),
        "classes": len({row["class_id"] for row in lessons}),
        "max_same_subject_per_day": {
            "count": worst_repeat[0],
            "where": worst_repeat[1],
        },
        "forced_doubles": forced_doubles,
        "worst_teacher_windows": worst_window_entry,
        "multi_subject_teachers": multi,
        "busy_share": round(share_busy, 3),
        "single_lesson_share": round(share_spare, 3),
    }


# ------------------------------------------------------------------ применение


def sync_assignments(
    journal,
    users: dict,
    classes: list[dict],
    needed: set[tuple[str, int]],
    *,
    db=None,
) -> None:
    """Синхронизирует назначения Journal с новым расписанием.

    Преподавателям пула выдаются их классы; назначения предметников,
    которые больше ничего не ведут, снимаются. Классные руководители
    и учителя прошлых (октябрьских) уроков сохраняются.
    """
    run = run_db if db is None else db
    teaching = run({"mode": "teacher_usage", "class_ids": []})
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


def set_subject_allowance(users: dict, *, executor=None) -> None:
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
    result = (executor or _run_schedule_module)(
        "schedule_service.set_subject_names", config
    )
    if result.returncode:
        raise DemoError("Не удалось подтвердить названия демо-предметов")


def _run_schedule_module(module: str, payload: dict):
    """Feeds one module of the Schedule container with JSON on stdin."""
    return subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "schedule-api",
            "/app/.venv/bin/python",
            "-m",
            module,
        ],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def rebuild_timetable(
    journal, days: list[date], classes: list[dict], users: dict, *, db=None
):
    """Repair path: reshuffles the exported lessons of a window in place.

    Kept for live public data (the run_db apply mode); the year scenario
    never goes through it. Refuses to continue when the demo classes
    hold lessons that no demo script manages.
    """
    run = run_db if db is None else db
    start = datetime.combine(days[0], time.min, TIMEZONE)
    end = datetime.combine(days[-1] + timedelta(days=1), time.min, TIMEZONE)
    teacher_ids = sorted(demo_teacher_ids(users))
    export = run(
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
    verify_state(lessons, users)
    protected = homework_lesson_ids()
    plan, teacher_by_key, plan_stats = plan_rebuild(lessons, protected, classes, users)
    needed = {(teacher, class_id) for (class_id, _s), teacher in teacher_by_key.items()}
    outcome = run({"mode": "apply", "plan": plan}) if plan else {"changed": 0}
    sync_assignments(journal, users, classes, needed, db=run)
    set_subject_allowance(users)
    print(
        f"Перестроено уроков: {outcome['changed']}. "
        f"Нагрузка учитель-день: {plan_stats['teacher_day_distribution']}. "
        f"teacher01 по дням: {plan_stats['teacher01_days']}.",
        flush=True,
    )
    return plan_stats


# ------------------------------------------------------------------
# Year scenario (spec sections 4 and 6)


def demo_teacher_ids(users: dict) -> set[str]:
    """Ids of every demo teacher account (*@demo.og.test)."""
    return {
        user["id"]
        for email, user in users.items()
        if email.startswith("teacher") and email.endswith("@demo.og.test")
    }


def export_year(
    db, class_ids: list[int], teacher_ids: list[str], calendar
) -> list[dict]:
    """Exports every lesson of the demo classes over the whole study year."""
    days = calendar.school_days()
    start = datetime.combine(days[0], time.min, TIMEZONE)
    end = datetime.combine(days[-1] + timedelta(days=1), time.min, TIMEZONE)
    return db(
        {
            "mode": "export",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "class_ids": class_ids,
            "teacher_ids": teacher_ids,
        }
    )


def teacher_pools(users: dict, grades) -> dict:
    """Builds the (grade, subject) -> teacher id pools for the plan.

    The pools follow the account scheme of tools/expand_demo_school.py:
    the class line teachers own mathematics, every other applicable
    subject gets one subject account per class line, so pools of
    different parallels never share a teacher.
    """
    id_of_subject = {name: subject_id for subject_id, name in SUBJECTS}
    pools: dict[tuple[str, str], list[str]] = {}
    for grade in grades:
        for subject in GRADE_CURRICULUM[grade]:
            subject_id = id_of_subject[subject]
            pool = []
            for code in CODES:
                email = (
                    emails(grade, code)
                    if subject_id == 1
                    else subject_teacher_email(grade, code, subject_id)
                )
                user = users.get(email)
                if user is not None:
                    pool.append(user["id"])
            if not pool:
                raise DemoError(
                    f"Нет учителей предмета {subject!r} параллели {grade} "
                    "в демо-учётках"
                )
            pools[(str(grade), subject)] = pool
    return pools


def year_plan_entries(classes: list[dict], users: dict, calendar) -> list[dict]:
    """Builds the create-mode plan of the whole study year.

    The deterministic plan of demo_year_plan.build_year_plan with the
    subject names mapped back to the school subject ids.
    """
    id_of_subject = {name: subject_id for subject_id, name in SUBJECTS}
    unknown = {
        subject
        for grade in GRADE_CURRICULUM
        for subject in GRADE_CURRICULUM[grade]
        if subject not in id_of_subject
    }
    if unknown:
        raise DemoError(f"Предметы таблицы часов вне каталога школы: {sorted(unknown)}")
    classes_by_grade: dict[int, list[int]] = defaultdict(list)
    grades = set()
    for row in classes:
        grade = grade_of(row["name"])
        grades.add(grade)
        classes_by_grade[grade].append(int(row["id"]))
    curriculum = {grade: GRADE_CURRICULUM[grade] for grade in sorted(grades)}
    plan = build_year_plan(
        curriculum,
        calendar,
        teacher_pools(users, sorted(grades)),
        classes_by_grade=classes_by_grade,
    )
    return [
        {
            "class_id": class_id,
            "subject_id": id_of_subject[subject],
            "teacher_id": teacher,
            "date": day.isoformat(),
            "period": period,
        }
        for class_id, subject, teacher, day, period in plan
    ]


def year_rebuild_due(report=None) -> bool:
    """True when the stored year fingerprint differs from the expected one.

    Mirrors the fingerprint check of rebuild_year (a missing or broken
    report file counts as a difference).
    """
    report = EXPANDED_SCHOOL_REPORT if report is None else report
    expected = year_fingerprint()
    stored: dict = {}
    if report.exists():
        try:
            stored = json.loads(report.read_text())
        except ValueError:
            stored = {}
    return stored.get("year_fingerprint") != expected


def wipe_year_lessons(journal, study_year: int, *, db=None) -> dict:
    """Deletes all lessons of the demo school classes before the expansion.

    The subject-catalogue step of expand_demo_school narrows the teacher
    allowance to the applicable teachers; lessons of the previous layout
    (taught by teachers that are no longer allowed) block that step, so
    a due full rebuild clears the lessons first. The wipe mode also
    drops the idempotency keys and the Redis day-cache keys.
    """
    db = run_db if db is None else db
    class_ids: list[int] = []
    offset = 0
    while True:
        page = journal.request(
            "GET",
            f"/internal/classes?study_year={study_year}&limit=100&offset={offset}",
        )
        class_ids.extend(int(row["id"]) for row in page)
        if len(page) < 100:
            break
        offset += 100
    if not class_ids:
        return {"wiped_lessons": 0, "wiped_keys": 0, "wiped_cache_keys": 0}
    return db({"mode": "wipe", "class_ids": sorted(set(class_ids))})


def rebuild_year(
    journal,
    classes: list[dict],
    users: dict,
    *,
    calendar=None,
    db=None,
    homework=None,
    report=None,
    set_allowance=None,
) -> dict:
    """Runs the study-year scenario: fingerprint, wipe, create, verify.

    The wipe order is fixed: the demo homework scenarios go first (the
    homework container), then the lessons with their idempotency keys
    and Redis day-cache keys (the Schedule container), then the
    emptiness is confirmed by an export before the create chunks run.
    A matching year fingerprint turns the run into the empty one: the
    lessons stay untouched, the scenarios are still wiped (they are
    recreated on the current study week by create_demo_data right
    after). Any fingerprint difference forces the full rebuild.

    Args:
        journal: Journal API client (assignment sync after create).
        classes: [{id, name}] rows of the demo school.
        users: demo email -> account dict.
        calendar: study-year calendar; defaults to the domain module.
        db: transport of balance_demo_lessons_db (run_db by default).
        homework: transport of balance_homework_scenarios_db.
        report: path of .demo-data/expanded-school.json.
        set_allowance: replaces set_subject_allowance in tests.

    Returns:
        The run summary: {"mode": "empty" | "rebuilt", ...}.
    """
    calendar = school_calendar if calendar is None else calendar
    db = run_db if db is None else db
    homework = run_homework_db if homework is None else homework
    report = EXPANDED_SCHOOL_REPORT if report is None else report
    class_ids = sorted({int(row["id"]) for row in classes})
    teacher_ids = sorted(demo_teacher_ids(users))
    expected = year_fingerprint()
    stored: dict = {}
    if report.exists():
        try:
            stored = json.loads(report.read_text())
        except ValueError:
            stored = {}
    matched = stored.get("year_fingerprint") == expected
    scenarios = homework(
        {"mode": "wipe", "teacher_ids": teacher_ids, "class_ids": class_ids}
    )
    if matched:
        lessons = export_year(db, class_ids, teacher_ids, calendar)
        healthy, stats = verify_state(lessons, users, classes, calendar)
        if healthy:
            print(
                "Отпечаток года совпал: уроки не тронуты (пустой прогон), "
                "сценарии ДЗ пересоздаются.",
                flush=True,
            )
            return {
                "mode": "empty",
                "lessons": len(lessons),
                "scenarios": scenarios,
                "verify": stats,
            }
        print(
            "Отпечаток года совпал, но проверки не прошли — полная пересборка.",
            flush=True,
        )
    wiped = db({"mode": "wipe", "class_ids": class_ids})
    leftover = [
        row
        for row in export_year(db, class_ids, teacher_ids, calendar)
        if row["class_id"] in set(class_ids)
    ]
    if leftover:
        raise DemoError(
            "Верификация пустоты не прошла: у демо-классов осталось "
            f"{len(leftover)} уроков после очистки"
        )
    plan = year_plan_entries(classes, users, calendar)
    created = db(
        {
            "mode": "create",
            "study_year": calendar.STUDY_YEAR[0].year,
            "plan": plan,
        }
    )
    if created.get("failed_chunk") is not None:
        raise DemoError(
            "Чанк записи года откатился; повторите запуск — завершённые "
            "класс-недели пропустятся. "
            f"Отчёт: {created['failed_chunk']}"
        )
    lessons = export_year(db, class_ids, teacher_ids, calendar)
    healthy, stats = verify_state(lessons, users, classes, calendar)
    if not healthy:
        raise DemoError(f"Проверка года не прошла: {stats.get('reason')}")
    needed = {(entry["teacher_id"], entry["class_id"]) for entry in plan}
    sync_assignments(journal, users, classes, needed, db=db)
    (set_allowance or set_subject_allowance)(users)
    stored.pop("timetable_version", None)
    stored.pop("dates", None)
    stored["year_fingerprint"] = expected
    stored["timetable"] = stats
    report.parent.mkdir(exist_ok=True)
    report.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Год пересобран: уроков {len(lessons)}, удалено при очистке "
        f"{wiped['lessons']}; проверки по всему году пройдены. "
        f"Отпечаток: {json.dumps(expected, sort_keys=True)}.",
        flush=True,
    )
    return {
        "mode": "rebuilt",
        "lessons": len(lessons),
        "plan": len(plan),
        "wiped": wiped,
        "scenarios": scenarios,
        "verify": stats,
    }
