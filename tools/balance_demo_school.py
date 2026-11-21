"""Распределяет занятия между предметниками, не создавая пересечений."""

import json
import random
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

from create_demo_data import ROOT, TIMEZONE, DemoError


def plan_teacher_load(rows, teacher_pools, expected):
    """Сначала учитывает защищённые уроки, затем заполняет дни предметников."""
    candidates, fixed = [], []
    for row in rows:
        expected_teachers = expected.get((row["class_id"], row["subject_id"]), set())
        (
            candidates
            if row["managed"]
            and row["version"] <= 4
            and bool(expected_teachers)
            and (
                row["teacher_id"] in expected_teachers
                or row["teacher_id"] in teacher_pools.get(row["subject_id"], [])
            )
            else fixed
        ).append(row)
    occupied = defaultdict(list)
    counts = defaultdict(int)
    weekly = defaultdict(int)

    def reserve(row, teacher):
        start, end = (
            datetime.fromisoformat(row["starts_at"]),
            datetime.fromisoformat(row["ends_at"]),
        )
        day = start.astimezone(TIMEZONE).date().isoformat()
        occupied[teacher].append((start, end))
        counts[(teacher, day)] += 1
        weekly[teacher] += 1

    for row in fixed:
        reserve(row, row["teacher_id"])
    grouped = defaultdict(list)
    for row in candidates:
        grouped[(row["class_id"], row["subject_id"])].append(row)
    fixed_teachers = defaultdict(set)
    for row in fixed:
        key = (row["class_id"], row["subject_id"])
        if key in grouped:
            fixed_teachers[key].add(row["teacher_id"])
    result = []
    by_subject = defaultdict(list)
    for key, lessons in grouped.items():
        by_subject[key[1]].append((key, lessons))
    for subject_id, subject_groups in sorted(by_subject.items()):
        pool = teacher_pools.get(subject_id, [])
        best = None
        for attempt in range(120):
            rng = random.Random(subject_id * 1000 + attempt)
            shuffled = list(subject_groups)
            rng.shuffle(shuffled)
            shuffled.sort(key=lambda item: -len(item[1]))
            local_occupied = {t: list(occupied[t]) for t in pool}
            local_counts = dict(counts)
            local_weekly = dict(weekly)
            selected = []
            failed = False
            for key, lessons in shuffled:
                class_id, _ = key
                forced = fixed_teachers.get(key, set())
                if len(forced) > 1:
                    raise DemoError(
                        f"У класса {class_id} несколько преподавателей одного предмета"
                    )
                per_day = defaultdict(int)
                intervals = []
                for row in lessons:
                    start = datetime.fromisoformat(row["starts_at"])
                    end = datetime.fromisoformat(row["ends_at"])
                    day = start.astimezone(TIMEZONE).date().isoformat()
                    intervals.append((start, end))
                    per_day[day] += 1
                choices = [
                    t
                    for t in pool
                    if (not forced or t in forced)
                    and all(
                        local_counts.get((t, d), 0) + n <= 6 for d, n in per_day.items()
                    )
                    and all(
                        end <= a or start >= b
                        for start, end in intervals
                        for a, b in local_occupied[t]
                    )
                ]
                if not choices:
                    failed = True
                    break
                order = {t: i for i, t in enumerate(pool)}
                teacher = min(
                    choices,
                    key=lambda t: (
                        -sum(local_counts.get((t, d), 0) for d in per_day),
                        -local_weekly.get(t, 0),
                        order[t],
                    ),
                )
                for row in lessons:
                    start, end = (
                        datetime.fromisoformat(row["starts_at"]),
                        datetime.fromisoformat(row["ends_at"]),
                    )
                    day = start.astimezone(TIMEZONE).date().isoformat()
                    local_occupied[teacher].append((start, end))
                    local_counts[(teacher, day)] = (
                        local_counts.get((teacher, day), 0) + 1
                    )
                    local_weekly[teacher] = local_weekly.get(teacher, 0) + 1
                selected.append((teacher, lessons))
            if failed:
                continue
            days = {
                datetime.fromisoformat(row["starts_at"])
                .astimezone(TIMEZONE)
                .date()
                .isoformat()
                for _, lessons in subject_groups
                for row in lessons
            }
            first = pool[0] if pool else None
            first_counts = [local_counts.get((first, day), 0) for day in days]
            score = (
                min(first_counts, default=0),
                sum(first_counts),
                sum(
                    n >= 5
                    for (teacher, day), n in local_counts.items()
                    if teacher in pool and day in days
                ),
                sum(
                    n * n
                    for (teacher, day), n in local_counts.items()
                    if teacher in pool and day in days
                ),
            )
            if best is None or score > best[0]:
                best = (score, selected)
        if best is None:
            raise DemoError(
                f"Не удалось распределить предмет {subject_id} без пересечений"
            )
        for teacher, lessons in best[1]:
            for row in lessons:
                reserve(row, teacher)
                if teacher != row["teacher_id"]:
                    before = {
                        name: value for name, value in row.items() if name != "managed"
                    }
                    result.append(
                        {"id": row["id"], "before": before, "teacher_id": teacher}
                    )
    return result


def run_db(data):
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
            "Не удалось безопасно пересобрать демо-расписание; изменения уроков откатились."
        )
    return json.loads(result.stdout)


def balance_school(journal, mapping, days, *, already_balanced=False):
    teacher_pools = defaultdict(list)
    expected = defaultdict(set)
    for item in mapping:
        teacher = item["teacher_id"]
        if teacher not in teacher_pools[item["subject_id"]]:
            teacher_pools[item["subject_id"]].append(teacher)
        expected[(item["class_id"], item["subject_id"])].update(
            (item["old_teacher_id"], teacher)
        )
    start = datetime.combine(days[0], datetime.min.time(), TIMEZONE)
    end = datetime.combine(days[-1] + timedelta(days=1), datetime.min.time(), TIMEZONE)
    rows = run_db(
        {
            "mode": "export",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "class_ids": sorted({item["class_id"] for item in mapping}),
            "teacher_ids": sorted({item["teacher_id"] for item in mapping}),
        }
    )
    plan = [] if already_balanced else plan_teacher_load(rows, teacher_pools, expected)
    assignments = {(entry["teacher_id"], entry["before"]["class_id"]) for entry in plan}
    for teacher_id, class_id in sorted(assignments):
        journal.request(
            "PUT", f"/internal/teachers/{teacher_id}/classes/{class_id}", ok=(201, 204)
        )
    outcome = run_db({"mode": "apply", "plan": plan}) if plan else {"changed": 0}
    print(f"Распределено уроков между предметниками: {outcome['changed']}.", flush=True)
    changed_teachers = {entry["id"]: entry["teacher_id"] for entry in plan}
    outcome["assignments"] = [
        {
            "class_id": row["class_id"],
            "subject_id": row["subject_id"],
            "teacher_id": changed_teachers.get(row["id"], row["teacher_id"]),
        }
        for row in rows
        if row["class_id"] in {item["class_id"] for item in mapping}
    ]
    return outcome
