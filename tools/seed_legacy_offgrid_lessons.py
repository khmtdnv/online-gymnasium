"""Локальная фикстура вне-сеточных уроков для приёмки сетки периодов.

После включения валидации API не позволяет создать вне-сеточный урок,
поэтому данные для приёмки пишет этот инструмент напрямую в локальную
базу Schedule (docker compose exec + psql). Создаёт уроки двух видов:
на неделе до effective_from со старым временем (для отображения блока
«Вне сетки») и с датой от effective_from вне сетки (для переноса).
Отказывается работать, если REMAP_API_BASE указывает не на localhost.
Повторный запуск идемпотентен: прежние строки фикстуры удаляются
точным совпадением перед вставкой; --clean только удаляет их.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Сетка и effective_from — из модуля сервиса расписания (без зависимостей).
SCHEDULE_SRC = str(ROOT / "services" / "schedule" / "src")
if SCHEDULE_SRC not in sys.path:
    sys.path.insert(0, SCHEDULE_SRC)

from schedule_service.domain.school_periods import EFFECTIVE_FROM, TIMEZONE

COMPOSE_SERVICE = "schedule-postgres"
LOCAL_HOSTS = ("localhost", "127.0.0.1")
DEFAULT_API_BASE = "http://localhost:8080"
PSQL = (
    'export PGPASSWORD="$POSTGRES_PASSWORD"; '
    'exec psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" '
    "-X -v ON_ERROR_STOP=1"
)

# Старое «нулевое» и послеурочное время для недели отображения: вне новой
# сетки периодов и вне плотного демо-дня 09:00–15:45 (иначе исключение
# пересечений Postgres отклоняет вставку для занятых классов).
LEGACY_SLOTS = (
    (time(8, 0), time(8, 45)),
    (time(16, 0), time(16, 45)),
)
# Время около периодов сетки для недели переноса (вне сетки, но рядом).
REMAP_SLOTS = (
    (
        (time(9, 3), time(9, 48)),
        (time(10, 2), time(10, 47)),
        (time(11, 7), time(11, 52)),
    ),
    (
        (time(13, 2), time(13, 47)),
        (time(15, 5), time(15, 50)),
    ),
)


class SeedError(Exception):
    """Останавливает инструмент при отказе доступа или сбое базы."""


@dataclass(frozen=True)
class Combo:
    """Существующая связка класс-преподаватель-предмет из базы расписания."""

    class_id: int
    teacher_id: str
    subject_id: int


@dataclass(frozen=True)
class FixtureRow:
    """Одна строка фикстуры с границами в местном времени школы."""

    combo: Combo
    day: date
    starts_at: datetime
    ends_at: datetime


def ensure_local_target() -> str:
    """Проверяет, что REMAP_API_BASE адресует локальный стек.

    Returns:
        Значение REMAP_API_BASE, прошедшее проверку.

    Raises:
        SeedError: Адрес указывает не на localhost/127.0.0.1.
    """
    base = os.environ.get("REMAP_API_BASE", DEFAULT_API_BASE)
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/:?]+)", base)
    host = match.group(1).lower() if match else base.lower()
    if host not in LOCAL_HOSTS:
        raise SeedError(
            f"REMAP_API_BASE ({base}) указывает не на localhost; "
            "фикстура работает только с локальным стеком"
        )
    return base


def psql(sql: str, *, csv_output: bool = False) -> str:
    """Выполняет SQL внутри контейнера базы Schedule.

    Args:
        sql: Скрипт SQL для psql на stdin.
        csv_output: Добавить --csv для разборчивого вывода запросов.

    Returns:
        Стандартный вывод psql.

    Raises:
        SeedError: Compose-стек недоступен или SQL не выполнен.
    """
    command = ["docker", "compose", "exec", "-T", COMPOSE_SERVICE, "sh", "-c"]
    shell = PSQL + (" --csv" if csv_output else "")
    result = subprocess.run(
        [*command, shell],
        input=sql,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SeedError(f"psql не выполнен: {detail}")
    return result.stdout


def load_combos() -> list[Combo]:
    """Читает существующие связки класс-преподаватель-предмет.

    Raises:
        SeedError: В базе нет уроков для переиспользования связок.
    """
    output = psql(
        "SELECT class_id, teacher_id, subject_id FROM scheduled_lessons "
        "GROUP BY 1, 2, 3 ORDER BY class_id, teacher_id, subject_id LIMIT 40;",
        csv_output=True,
    )
    combos = []
    for row in csv.DictReader(io.StringIO(output)):
        combos.append(
            Combo(
                class_id=int(row["class_id"]),
                teacher_id=str(uuid.UUID(row["teacher_id"])),
                subject_id=int(row["subject_id"]),
            )
        )
    if not combos:
        raise SeedError("В базе расписания нет уроков; сначала создайте демо-данные")
    return combos


def load_planned_intervals(window_start: datetime, window_end: datetime) -> list[tuple]:
    """Читает плановые уроки окна дат для проверки пересечений.

    Args:
        window_start: Начало окна (осознанная дата UTC).
        window_end: Конец окна (осознанная дата UTC).

    Returns:
        Кортежи (class_id, teacher_id, starts_at, ends_at).
    """
    output = psql(
        "SELECT class_id, teacher_id, starts_at, ends_at "
        "FROM scheduled_lessons "
        f"WHERE status = 'planned' AND starts_at < {sql_literal(window_end)} "
        f"AND ends_at > {sql_literal(window_start)} "
        "ORDER BY starts_at;",
        csv_output=True,
    )
    rows = []
    for row in csv.DictReader(io.StringIO(output)):
        rows.append(
            (
                int(row["class_id"]),
                str(uuid.UUID(row["teacher_id"])),
                datetime.fromisoformat(row["starts_at"]),
                datetime.fromisoformat(row["ends_at"]),
            )
        )
    return rows


def legacy_days() -> list[date]:
    """Учебные дни (Пн–Сб) недели перед effective_from."""
    monday_before = EFFECTIVE_FROM - timedelta(days=EFFECTIVE_FROM.weekday() + 7)
    return [monday_before + timedelta(days=offset) for offset in range(6)]


def remap_days() -> list[date]:
    """Первые учебные дни горизонта переноса (от effective_from)."""
    days = []
    day = EFFECTIVE_FROM
    while len(days) < len(REMAP_SLOTS):
        if day.weekday() != 6:
            days.append(day)
        day += timedelta(days=1)
    return days


def slot_intervals() -> set[tuple[datetime, datetime]]:
    """Точные границы всех слотов фикстуры в UTC.

    Возвращаемое множество используется для самоисключения: строки
    предыдущего запуска фикстуры лежат точно на границах слотов и не
    должны мешать выбору связок при повторном запуске.
    """
    intervals = set()
    for day, slots in [(day, LEGACY_SLOTS) for day in legacy_days()] + list(
        zip(remap_days(), REMAP_SLOTS)
    ):
        for start_local, end_local in slots:
            intervals.add(
                (
                    datetime.combine(day, start_local, TIMEZONE).astimezone(UTC),
                    datetime.combine(day, end_local, TIMEZONE).astimezone(UTC),
                )
            )
    return intervals


def overlaps(
    combo: Combo, starts_at: datetime, ends_at: datetime, planned: list[tuple]
) -> bool:
    """Проверяет пересечение интервала с плановыми уроками класса/учителя."""
    return any(
        (class_id == combo.class_id or teacher_id == combo.teacher_id)
        and starts_at < row_end
        and ends_at > row_start
        for class_id, teacher_id, row_start, row_end in planned
    )


def build_rows(combos: list[Combo], planned: list[tuple]) -> list[FixtureRow]:
    """Собирает строки фикстуры, обходя пересечения с плановыми уроками.

    Args:
        combos: Кандидаты связок класс-преподаватель-предмет.
        planned: Плановые уроки окна дат (class, teacher, start, end).

    Returns:
        Строки фикстуры; слот пропускается с предупреждением, если ни одна
        связка не свободна.
    """
    occupied = list(planned)
    rows: list[FixtureRow] = []
    plan = [(day, slot) for day in legacy_days() for slot in LEGACY_SLOTS] + [
        (day, slot) for day, slots in zip(remap_days(), REMAP_SLOTS) for slot in slots
    ]
    for index, (day, (start_local, end_local)) in enumerate(plan):
        starts_at = datetime.combine(day, start_local, TIMEZONE)
        ends_at = datetime.combine(day, end_local, TIMEZONE)
        # Связки перебираются с ротацией, чтобы фикстура распределялась
        # по разным классам и преподавателям, а не по первой свободной.
        rotation = index % len(combos)
        ordered = combos[rotation:] + combos[:rotation]
        combo = next(
            (
                candidate
                for candidate in ordered
                if not overlaps(candidate, starts_at, ends_at, occupied)
            ),
            None,
        )
        if combo is None:
            print(
                f"Пропущено: нет свободной связки для {day} "
                f"{start_local:%H:%M}–{end_local:%H:%M}",
                file=sys.stderr,
            )
            continue
        rows.append(FixtureRow(combo, day, starts_at, ends_at))
        occupied.append((combo.class_id, combo.teacher_id, starts_at, ends_at))
    return rows


def sql_literal(value: datetime) -> str:
    """Формирует безопасный литерал timestamptz в UTC."""
    moment = value.astimezone(UTC)
    return f"'{moment:%Y-%m-%d %H:%M:%S+00}'::timestamptz"


def row_tuple(row: FixtureRow) -> str:
    """Формирует кортеж значений одной строки для SQL."""
    combo = row.combo
    return (
        f"({combo.class_id}, '{combo.teacher_id}'::uuid, {combo.subject_id}, "
        f"{sql_literal(row.starts_at)}, {sql_literal(row.ends_at)}, 'planned')"
    )


def delete_sql(rows: list[FixtureRow]) -> str:
    """Формирует удаление строк фикстуры по точному совпадению."""
    tuples = ", ".join(row_tuple(row) for row in rows)
    return (
        "DELETE FROM scheduled_lessons "
        f"WHERE (class_id, teacher_id, subject_id, starts_at, ends_at, status) "
        f"IN ({tuples});"
    )


def insert_sql(rows: list[FixtureRow]) -> str:
    """Формирует вставку строк фикстуры (id и version — серверные default)."""
    tuples = ", ".join(row_tuple(row) for row in rows)
    return (
        "INSERT INTO scheduled_lessons "
        "(class_id, teacher_id, subject_id, starts_at, ends_at, status) "
        f"VALUES {tuples};"
    )


def fetch_ids(rows: list[FixtureRow]) -> str:
    """Перечитывает идентификаторы вставленных строк фикстуры."""
    tuples = ", ".join(
        f"({row.combo.class_id}, '{row.combo.teacher_id}'::uuid, "
        f"{sql_literal(row.starts_at)})"
        for row in rows
    )
    output = psql(
        "SELECT id, class_id, starts_at, ends_at FROM scheduled_lessons "
        f"WHERE (class_id, teacher_id, starts_at) IN ({tuples}) "
        "AND status = 'planned' ORDER BY id;",
        csv_output=True,
    )
    return output.strip()


def clean(rows: list[FixtureRow]) -> None:
    """Удаляет только строки фикстуры по точному совпадению."""
    with_count = re.search(r"DELETE (\d+)", psql(delete_sql(rows)))
    print(f"Удалено строк фикстуры: {with_count.group(1) if with_count else '?'}")
    print(
        "Уроки, уже перенесённые инструментом remap_offgrid_lessons.py, "
        "сохранены: их новое время в сетке легитимно"
    )


def seed(rows: list[FixtureRow]) -> None:
    """Выполняет идемпотентную вставку строк фикстуры одной транзакцией."""
    script = "BEGIN;\n" + delete_sql(rows) + "\n" + insert_sql(rows) + "\nCOMMIT;\n"
    insert_count = re.search(r"INSERT 0 (\d+)", psql(script))
    print(f"Вставлено строк фикстуры: {insert_count.group(1) if insert_count else '?'}")
    print(fetch_ids(rows))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы запуска фикстуры."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Только удалить строки фикстуры (без вставки)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Точка входа: проверяет локальность, собирает и пишет фикстуру.

    Коды выхода: 0 — успешно; 1 — отказ доступа или сбой базы.
    """
    args = parse_args(argv)
    try:
        base = ensure_local_target()
        combos = load_combos()
        window_start = datetime.combine(legacy_days()[0], time.min, TIMEZONE)
        last_day = remap_days()[-1]
        window_end = datetime.combine(last_day, time.max, TIMEZONE)
        own = slot_intervals()
        # Строки предыдущего запуска фикстуры исключаются из проверки
        # пересечений: их удалит эта же транзакция перед вставкой.
        planned = [
            row
            for row in load_planned_intervals(window_start, window_end)
            if (row[2], row[3]) not in own
        ]
        rows = build_rows(combos, planned)
    except SeedError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"Цель: {base} (локальный стек), сервис {COMPOSE_SERVICE}")
    print(
        f"Неделя отображения: {legacy_days()[0]}…{legacy_days()[-1]}; "
        f"дни переноса: {remap_days()[0]} и {remap_days()[-1]}; "
        f"effective_from={EFFECTIVE_FROM}"
    )
    if not rows:
        print("Нет строк для вставки", file=sys.stderr)
        return 1
    for row in rows:
        kind = "отображение" if row.day < EFFECTIVE_FROM else "перенос"
        print(
            f"{kind}: {row.day} {row.starts_at:%H:%M}–{row.ends_at:%H:%M} "
            f"(местное) · класс {row.combo.class_id} · "
            f"преподаватель {row.combo.teacher_id} · "
            f"предмет {row.combo.subject_id}"
        )
    try:
        if args.clean:
            clean(rows)
        else:
            seed(rows)
    except SeedError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
