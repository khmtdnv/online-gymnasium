"""Перенос вне-сеточных уроков на сетку семи периодов (этап 2 спецификации).

Режимы: --dry-run (по умолчанию) — отчёт с предлагаемым периодом;
--apply — перенос через административный API Gateway; --check — пост-проверка.
Вход: REMAP_ADMIN_EMAIL и REMAP_ADMIN_PASSWORD, адрес REMAP_API_BASE
(по умолчанию http://localhost:8080). Логика переноса — чистые функции
без ввода-вывода; HTTP-слой поверх них максимально тонкий.

--check сразу после --apply может увидеть устаревшие данные: чтение
дневного расписания идёт через кеш Schedule, инвалидация которого
асинхронная; пост-проверка по runbook выполняется после smoke-шагов,
при локальном прогоне достаточно повторить --check через ~20 секунд.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]

# Единственный источник сетки учебного дня — модуль сервиса расписания
# без зависимостей вне stdlib (локальных копий сетки в инструменте нет).
SCHEDULE_SRC = str(ROOT / "services" / "schedule" / "src")
if SCHEDULE_SRC not in sys.path:
    sys.path.insert(0, SCHEDULE_SRC)

from schedule_service.domain.school_periods import (
    EFFECTIVE_FROM,
    PERIODS,
    TIMEZONE,
    SchoolPeriod,
    period_for,
)

DEFAULT_API_BASE = "http://localhost:8080"
HORIZON_CALENDAR_DAYS = 14
SUNDAY = 6
PLANNED = "planned"
EXIT_OK = 0
EXIT_UNPLACED = 1
EXIT_CONFIG = 2
EXIT_API = 3


class RemapError(Exception):
    """Останавливает инструмент при сбое сети или неожиданном ответе API."""


class NoRedirect(HTTPRedirectHandler):
    """Не позволяет отправить токен на адрес перенаправления."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    """HTTP-клиент зеркально классу Api из create_demo_data.py."""

    def __init__(self, base: str, headers: dict | None = None):
        self.base = base
        self.headers = headers or {}
        self.opener = build_opener(NoRedirect())
        self.last_status = 0

    def request(self, method, path, body=None, *, ok=(200,), headers=None):
        """Возвращает декодированный JSON; статус сохраняется в last_status.

        Args:
            method: HTTP-метод.
            path: Относительный путь API.
            body: JSON-объект запроса.
            ok: Допустимые HTTP-статусы.
            headers: Дополнительные заголовки одного запроса.

        Returns:
            Разобранный JSON, байты либо None для пустого ответа.

        Raises:
            RemapError: Сеть или статус не позволяют подтвердить результат.
        """
        if not path.startswith("/") or path.startswith("//"):
            raise RemapError("Ожидался относительный путь API")
        request_headers = {**self.headers, **(headers or {})}
        if body is not None:
            body = json.dumps(body, ensure_ascii=False).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(
            self.base + path, data=body, headers=request_headers, method=method
        )
        try:
            response = self.opener.open(request, timeout=45)
        except HTTPError as exc:
            response = exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RemapError(f"Нет ответа {method} {path}") from exc
        with response:
            self.last_status = response.code
            content = response.read()
            if response.code not in ok:
                # Не печатаем тело ответа: оно может содержать чужие данные.
                raise RemapError(f"{method} {path}: HTTP {response.code}")
            if response.code == 404 or not content:
                return None
            if "json" in response.headers.get("Content-Type", ""):
                return json.loads(content)
            return content


@dataclass(frozen=True)
class LessonRecord:
    """Урок в терминах административного контракта (без ввода-вывода)."""

    id: int
    class_id: int
    teacher_id: str
    subject_id: int
    starts_at: datetime
    ends_at: datetime
    status: str
    version: int


@dataclass(frozen=True)
class RemapDecision:
    """Решение детерминированного правила для одного вне-сеточного урока."""

    lesson: LessonRecord
    period: SchoolPeriod | None
    new_starts_at: datetime | None
    new_ends_at: datetime | None

    @property
    def placed(self) -> bool:
        """Признак успешного подбора периода (False — «не размещён»)."""
        return self.period is not None


def parse_lesson(row: dict) -> LessonRecord:
    """Собирает запись урока из строки административного ответа.

    Args:
        row: Элемент ответа GET /api/v1/schedule/lessons.

    Returns:
        Неизменяемая запись урока с осознанными датами UTC.

    Raises:
        RemapError: Строка не соответствует контракту инструмента.
    """
    try:
        return LessonRecord(
            id=int(row["id"]),
            class_id=int(row["class_id"]),
            teacher_id=str(row["teacher_id"]),
            subject_id=int(row["subject_id"]),
            starts_at=datetime.fromisoformat(str(row["starts_at"])),
            ends_at=datetime.fromisoformat(str(row["ends_at"])),
            status=str(row["status"]),
            version=int(row["version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RemapError(f"Некорректная строка урока: {exc!r}") from exc


def local_interval(lesson: LessonRecord) -> tuple[datetime, datetime]:
    """Возвращает границы урока в местном времени школы."""
    return (
        lesson.starts_at.astimezone(TIMEZONE),
        lesson.ends_at.astimezone(TIMEZONE),
    )


def school_date(lesson: LessonRecord) -> date:
    """Возвращает школьную дату урока (дата локального начала)."""
    return local_interval(lesson)[0].date()


def horizon_school_days(
    calendar_days: int = HORIZON_CALENDAR_DAYS,
) -> list[date]:
    """Учебные дни фиксированного горизонта чтения: Пн–Сб включительно.

    Args:
        calendar_days: Календарных дней после effective_from (включительно).

    Returns:
        Даты от effective_from до effective_from + calendar_days
        без воскресений.
    """
    days = []
    for offset in range(calendar_days + 1):
        day = EFFECTIVE_FROM + timedelta(days=offset)
        if day.weekday() != SUNDAY:
            days.append(day)
    return days


def needs_remap(lesson: LessonRecord) -> bool:
    """Признак урока, подлежащего переносу по правилам спецификации.

    Урок обязан лечь в сетку, если его школьная дата не раньше
    effective_from, и вне сетки, если его локальные границы не совпадают
    точно ни с одним периодом.
    """
    return (
        school_date(lesson) >= EFFECTIVE_FROM
        and period_for(lesson.starts_at, lesson.ends_at) is None
    )


def offgrid_lessons(lessons: Sequence[LessonRecord]) -> list[LessonRecord]:
    """Сортирует уроки для отчёта --check (детерминированный порядок)."""
    return sorted(
        (lesson for lesson in lessons if needs_remap(lesson)),
        key=lambda lesson: (local_interval(lesson)[0], lesson.id),
    )


def _abs_time_delta(first: time, second: time) -> timedelta:
    """Абсолютная разница двух значений времени одного дня."""
    return abs(datetime.combine(date.min, first) - datetime.combine(date.min, second))


def nearest_period(local_start: time) -> SchoolPeriod:
    """Период с минимальной разницей начала с данным временем.

    При равенстве разницы возвращается более ранний период.
    """
    best = PERIODS[0]
    best_delta = _abs_time_delta(best.start_at, local_start)
    for period in PERIODS[1:]:
        delta = _abs_time_delta(period.start_at, local_start)
        if delta < best_delta:
            best = period
            best_delta = delta
    return best


def collect_occupancy(
    lessons: Sequence[LessonRecord],
) -> tuple[set[tuple[date, int, int]], set[tuple[date, str, int]]]:
    """Занятость периодов неотменёнными уроками, уже лежащими в сетке.

    Returns:
        Пара множеств: занятые периоды классов (дата, class_id, номер)
        и преподавателей (дата, teacher_id, номер).
    """
    class_busy: set[tuple[date, int, int]] = set()
    teacher_busy: set[tuple[date, str, int]] = set()
    for lesson in lessons:
        if lesson.status != PLANNED:
            continue
        period = period_for(lesson.starts_at, lesson.ends_at)
        if period is None:
            continue
        day = school_date(lesson)
        class_busy.add((day, lesson.class_id, period.number))
        teacher_busy.add((day, lesson.teacher_id, period.number))
    return class_busy, teacher_busy


def first_free_period(
    min_number: int,
    day: date,
    class_id: int,
    teacher_id: str,
    class_busy: set[tuple[date, int, int]],
    teacher_busy: set[tuple[date, str, int]],
) -> SchoolPeriod | None:
    """Первый свободный период по возрастанию номера от min_number.

    Предыдущие периоды (с меньшим номером) не рассматриваются.
    """
    for period in PERIODS:
        if period.number < min_number:
            continue
        if (day, class_id, period.number) in class_busy:
            continue
        if (day, teacher_id, period.number) in teacher_busy:
            continue
        return period
    return None


def period_bounds(day: date, period: SchoolPeriod) -> tuple[datetime, datetime]:
    """Точные границы периода в школьной дате как осознанные даты UTC."""
    return (
        datetime.combine(day, period.start_at, TIMEZONE).astimezone(UTC),
        datetime.combine(day, period.end_at, TIMEZONE).astimezone(UTC),
    )


def _decision_for(lesson: LessonRecord, period: SchoolPeriod) -> RemapDecision:
    """Собирает решение с новыми границами равными границам периода."""
    starts_at, ends_at = period_bounds(school_date(lesson), period)
    return RemapDecision(
        lesson=lesson, period=period, new_starts_at=starts_at, new_ends_at=ends_at
    )


def plan_remaps(lessons: Sequence[LessonRecord]) -> list[RemapDecision]:
    """Детерминированный план переноса всех подлежащих уроков.

    Кандидат — период того же школьного дня с минимальной разницей
    начала с локальным началом урока (при равенстве — более ранний).
    Занятый период заменяется следующим свободным по возрастанию номера;
    предыдущие не рассматриваются. Отменённые уроки переносятся
    в ближайший период без проверок и не занимают периоды. Правило
    не зависит от порядка входных данных: цели сортируются, занятость
    учитывает уже принятые решения.

    Args:
        lessons: Все уроки горизонта, собранные из ответов API.

    Returns:
        Решения в порядке обработки; урок без свободного периода —
        с period=None («не размещён»).
    """
    class_busy, teacher_busy = collect_occupancy(lessons)
    targets = sorted(
        (lesson for lesson in lessons if needs_remap(lesson)),
        key=lambda lesson: (local_interval(lesson)[0], lesson.id),
    )
    decisions: list[RemapDecision] = []
    for lesson in targets:
        local_start = local_interval(lesson)[0].time()
        candidate = nearest_period(local_start)
        if lesson.status != PLANNED:
            decisions.append(_decision_for(lesson, candidate))
            continue
        day = school_date(lesson)
        chosen = first_free_period(
            candidate.number,
            day,
            lesson.class_id,
            lesson.teacher_id,
            class_busy,
            teacher_busy,
        )
        if chosen is None:
            decisions.append(
                RemapDecision(
                    lesson=lesson, period=None, new_starts_at=None, new_ends_at=None
                )
            )
            continue
        class_busy.add((day, lesson.class_id, chosen.number))
        teacher_busy.add((day, lesson.teacher_id, chosen.number))
        decisions.append(_decision_for(lesson, chosen))
    return decisions


def login(base: str, email: str, password: str) -> Api:
    """Входит администратором и возвращает клиент с Bearer-токеном.

    Args:
        base: Адрес Gateway из REMAP_API_BASE.
        email: Email администратора из REMAP_ADMIN_EMAIL.
        password: Пароль из REMAP_ADMIN_PASSWORD (не логируется).

    Returns:
        Клиент с заголовком Authorization для административных запросов.

    Raises:
        RemapError: Вход не подтверждён или не вернул access_token.
    """
    origin = os.environ.get("REMAP_PUBLIC_ORIGIN", base)
    public = Api(base, {"Origin": origin})
    result = public.request(
        "POST", "/api/v1/auth/login", {"email": email, "password": password}
    )
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        raise RemapError("Вход не вернул access_token")
    return Api(base, {"Authorization": "Bearer " + token})


def load_classes(api: Api) -> list[dict]:
    """Читает список классов из справочника административной формы.

    Raises:
        RemapError: Справочник недоступен или не содержит классы.
    """
    directory = api.request("GET", "/api/v1/schedule/directory")
    classes = directory.get("classes") if isinstance(directory, dict) else None
    if not isinstance(classes, list) or not classes:
        raise RemapError("Справочник не вернул классы")
    return classes


def fetch_lessons(api: Api, classes: Sequence[dict]) -> list[dict]:
    """Собирает уроки каждого класса на каждый учебный день горизонта.

    Один и тот же урок может вернуться за соседние запрошенные даты,
    поэтому строки дедуплицируются по идентификатору.
    """
    rows: dict[int, dict] = {}
    for klass in classes:
        class_id = int(klass["id"])
        for day in horizon_school_days():
            path = (
                f"/api/v1/schedule/lessons?class_id={class_id}&date={day.isoformat()}"
            )
            payload = api.request("GET", path)
            if not isinstance(payload, list):
                raise RemapError(f"Ответ {path} не является списком уроков")
            for row in payload:
                if not isinstance(row, dict) or "id" not in row:
                    raise RemapError(f"Некорректная строка урока в ответе {path}")
                rows[int(row["id"])] = row
    return list(rows.values())


def class_names(classes: Sequence[dict]) -> dict[int, str]:
    """Сопоставляет идентификаторы классов их именам из справочника."""
    return {int(row["id"]): str(row.get("name", row["id"])) for row in classes}


def format_current(lesson: LessonRecord) -> str:
    """Текущее время урока в местном времени школы."""
    start_local, end_local = local_interval(lesson)
    return f"{start_local:%Y-%m-%d %H:%M}–{end_local:%H:%M}"


def print_report(decisions: Sequence[RemapDecision], names: dict[int, str]) -> None:
    """Печатает отчёт dry-run: урок, время, класс, преподаватель, период."""
    for decision in decisions:
        lesson = decision.lesson
        klass = names.get(lesson.class_id, str(lesson.class_id))
        if decision.period is None:
            target = "НЕ РАЗМЕЩЁН: нет свободного периода в дне"
        else:
            target = (
                f"период {decision.period.number} "
                f"{decision.period.start_at:%H:%M}–{decision.period.end_at:%H:%M}"
            )
        print(
            f"Урок {lesson.id}: {format_current(lesson)} (местное) · "
            f"класс {klass} · преподаватель {lesson.teacher_id} · "
            f"предмет {lesson.subject_id} → {target}"
        )


def print_offgrid(lessons: Sequence[LessonRecord], names: dict[int, str]) -> None:
    """Печатает список вне-сеточных уроков для режима --check."""
    for lesson in lessons:
        klass = names.get(lesson.class_id, str(lesson.class_id))
        print(
            f"Урок {lesson.id}: {format_current(lesson)} (местное) · "
            f"класс {klass} · преподаватель {lesson.teacher_id} · "
            f"предмет {lesson.subject_id} · статус {lesson.status}"
        )


def apply_decision(
    api: Api,
    decision: RemapDecision,
    class_busy: set[tuple[date, int, int]],
    teacher_busy: set[tuple[date, str, int]],
) -> SchoolPeriod:
    """Переносит один урок; при 409 берёт следующий свободный период.

    Args:
        api: Клиент с токеном администратора.
        decision: Решение плана (гарантированно размещённое).
        class_busy: Занятость классов, обновляется успешным переносом.
        teacher_busy: Занятость преподавателей, обновляется переносом.

    Returns:
        Период, в который урок фактически записан.

    Raises:
        RemapError: Свободных периодов не осталось или ответ API не 200/409.
    """
    lesson = decision.lesson
    day = school_date(lesson)
    assert decision.period is not None
    period = decision.period
    while period is not None:
        starts_at, ends_at = period_bounds(day, period)
        api.request(
            "PATCH",
            f"/api/v1/schedule/lessons/{lesson.id}",
            {
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "expected_version": lesson.version,
            },
            ok=(200, 409),
        )
        if api.last_status == 200:
            class_busy.add((day, lesson.class_id, period.number))
            teacher_busy.add((day, lesson.teacher_id, period.number))
            return period
        # 409 — страховка от гонок: период занят, берём следующий свободный.
        class_busy.add((day, lesson.class_id, period.number))
        teacher_busy.add((day, lesson.teacher_id, period.number))
        period = first_free_period(
            period.number + 1,
            day,
            lesson.class_id,
            lesson.teacher_id,
            class_busy,
            teacher_busy,
        )
    raise RemapError(f"Урок {lesson.id}: нет свободного периода после 409")


def run_dry_run(lessons: Sequence[LessonRecord], names: dict[int, str]) -> int:
    """Печатает отчёт preflight-инвентаризации и возвращает код выхода."""
    decisions = plan_remaps(lessons)
    unplaced = [decision for decision in decisions if not decision.placed]
    print(
        f"Горизонт: {horizon_school_days()[0]}…{horizon_school_days()[-1]} "
        f"({len(horizon_school_days())} учебных дней), "
        f"effective_from={EFFECTIVE_FROM}"
    )
    print(f"Проверено уроков: {len(lessons)}; вне сетки: {len(decisions)}")
    print_report(decisions, names)
    if unplaced:
        print(f"Не размещено уроков: {len(unplaced)}", file=sys.stderr)
        return EXIT_UNPLACED
    return EXIT_OK


def run_check(lessons: Sequence[LessonRecord], names: dict[int, str]) -> int:
    """Пост-проверка: 0, если вне-сеточных уроков горизонта нет, иначе 1."""
    offgrid = offgrid_lessons(lessons)
    print(f"Проверено уроков: {len(lessons)}")
    if not offgrid:
        print(f"Вне-сеточных уроков со школьной датой от {EFFECTIVE_FROM} нет")
        return EXIT_OK
    print(f"Вне сетки уроков: {len(offgrid)}")
    print_offgrid(offgrid, names)
    return EXIT_UNPLACED


def run_apply(api: Api, lessons: Sequence[LessonRecord], names: dict[int, str]) -> int:
    """Выполняет детерминированный перенос через административный API.

    Стоп-условия до начала: хоть один урок «не размещён». Стоп-условие
    в середине: любая ошибка API кроме 409 (409 — сигнал взять следующий
    период); в обоих случаях выполнение завершается ненулевым кодом.
    """
    decisions = plan_remaps(lessons)
    unplaced = [decision for decision in decisions if not decision.placed]
    if unplaced:
        print_report(decisions, names)
        print(
            f"Перенос не выполнен: не размещено уроков {len(unplaced)} (стоп-условие)",
            file=sys.stderr,
        )
        return EXIT_UNPLACED
    class_busy, teacher_busy = collect_occupancy(lessons)
    for decision in decisions:
        period = apply_decision(api, decision, class_busy, teacher_busy)
        print(
            f"Урок {decision.lesson.id}: {format_current(decision.lesson)} "
            f"(местное) → период {period.number} "
            f"{period.start_at:%H:%M}–{period.end_at:%H:%M}"
        )
    print(f"Перенесено уроков: {len(decisions)}")
    return EXIT_OK


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы режима запуска."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Отчёт с предлагаемыми периодами (режим по умолчанию)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Перенос через PATCH административного API",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Пост-проверка: 0, если вне-сеточных уроков нет",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа: читает окружение, собирает данные и выполняет режим.

    Коды выхода: 0 — успешно; 1 — «не размещён»/вне сетки; 2 — не заданы
    учётные данные; 3 — ошибка API.
    """
    args = parse_args(argv)
    base = os.environ.get("REMAP_API_BASE", DEFAULT_API_BASE)
    email = os.environ.get("REMAP_ADMIN_EMAIL", "")
    password = os.environ.get("REMAP_ADMIN_PASSWORD", "")
    if not email or not password:
        print(
            "Задайте REMAP_ADMIN_EMAIL и REMAP_ADMIN_PASSWORD (учётная запись "
            "администратора, подготовленная через Backoffice)",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    try:
        api = login(base, email, password)
        classes = load_classes(api)
        rows = fetch_lessons(api, classes)
    except RemapError as exc:
        print(f"Ошибка API: {exc}", file=sys.stderr)
        return EXIT_API
    lessons = [parse_lesson(row) for row in rows]
    names = class_names(classes)
    if args.check:
        return run_check(lessons, names)
    if args.apply:
        try:
            return run_apply(api, lessons, names)
        except RemapError as exc:
            print(f"Перенос прерван: {exc}", file=sys.stderr)
            return EXIT_API
    return run_dry_run(lessons, names)


if __name__ == "__main__":
    sys.exit(main())
