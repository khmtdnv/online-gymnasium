"""Создаёт локальную демо-школу через API, не очищая базы и чужие записи.

Запуск из корня проекта: python3 tools/create_demo_data.py --apply
Без --apply выполняется только проверка доступности и показывается план.
Секреты читаются из разрешённой конфигурации Compose и не выводятся в отчёт.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import struct
import subprocess
import sys
import time
import zlib
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]

# Единственный источник сетки учебного дня — модуль сервиса расписания;
# он не имеет зависимостей вне stdlib, поэтому инструменты демо-данных
# импортируют его напрямую (локальных копий сетки здесь нет).
SCHEDULE_SRC = str(ROOT / "services" / "schedule" / "src")
if SCHEDULE_SRC not in sys.path:
    sys.path.insert(0, SCHEDULE_SRC)

from schedule_service.domain import school_calendar
from schedule_service.domain.school_periods import PERIODS, TIMEZONE

DEMO_PASSWORD = "DemoSchool2026!"
REPORT = ROOT / ".demo-data" / "report.json"
SESSIONS: list[Api] = []
LABELS = (
    "Можно выполнить: ответа пока нет",
    "Работа ожидает проверки преподавателем",
    "Работа возвращена на исправление",
    "Повторная попытка после замечания",
    "Работа проверена: оценка 4",
    "Файлы преподавателя и учеников",
    "Срок привязан к отменённому уроку",
)


class DemoError(Exception):
    """Безопасно останавливает наполнение при конфликте или сбое сервиса."""


class NoRedirect(HTTPRedirectHandler):
    """Не позволяет отправить служебный токен на адрес перенаправления."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    """Выполняет локальные запросы с ограниченным ожиданием, без слепых повторов."""

    def __init__(self, base: str, headers: dict | None = None):
        self.base = base
        self.headers = headers or {}
        self.opener = build_opener(NoRedirect())
        self.session_cookie = ""
        self.last_cookie = ""

    def request(self, method, path, body=None, *, ok=(200,), headers=None):
        """Возвращает JSON/байты; неожиданный статус останавливает скрипт.

        Args:
            method: HTTP-метод.
            path: Относительный путь локального API.
            body: JSON-объект либо готовые байты multipart.
            ok: Допустимые HTTP-статусы.
            headers: Дополнительные заголовки одного запроса.

        Returns:
            Декодированный JSON, байты файла либо None для пустого ответа.

        Raises:
            DemoError: Сеть/статус не позволяют подтвердить результат.
        """
        if not path.startswith("/") or path.startswith("//"):
            raise DemoError("Ожидался относительный путь API")
        request_headers = {**self.headers, **(headers or {})}
        if body is not None and not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(
            self.base + path, data=body, headers=request_headers, method=method
        )
        attempts = 0
        while True:
            try:
                response = self.opener.open(request, timeout=45)
            except HTTPError as exc:
                response = exc
            except (URLError, TimeoutError, OSError) as exc:
                raise DemoError(
                    f"Нет подтверждения {method} {path}; безопасно повторите скрипт"
                ) from exc
            with response:
                status = response.code
                self.last_cookie = response.headers.get("Set-Cookie", "")
                content = response.read()
                content_type = response.headers.get("Content-Type", "")
                retry_after = response.headers.get("Retry-After", "")
            if status != 429 or attempts >= 7:
                break
            # Демо-школа логинится часто: уважаем лимит входа и ждём.
            delay = (
                float(retry_after)
                if retry_after.replace(".", "", 1).isdigit()
                else float(min(2**attempts, 20))
            )
            time.sleep(delay)
            attempts += 1
        if status not in ok:
            # Не печатаем запросы, токены, пароли или чужие ответы сервиса.
            raise DemoError(f"{method} {path}: HTTP {status}")
        if status == 404 or not content:
            return None
        if "json" in content_type:
            return json.loads(content)
        return content


def build_accounts() -> list[dict]:
    """Описывает 79 учёток с отдельными демо-email и обязательными именами."""
    result = []
    surnames = (
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
    )
    names = ("Артём", "Иван", "Максим", "Даниил", "Никита")
    for grade, surname in enumerate(surnames, 1):
        result.append(
            {
                "email": f"teacher{grade:02}@demo.og.test",
                "role": "teacher",
                "first_name": "Александр",
                "last_name": surname,
                "middle_name": "Сергеевич",
            }
        )
        result.append(
            {
                "email": f"parent{grade:02}@demo.og.test",
                "role": "parent",
                "first_name": "Сергей",
                "last_name": surname,
                "middle_name": "Иванович",
            }
        )
        for index, name in enumerate(names, 1):
            result.append(
                {
                    "email": f"student{grade:02}.{index}@demo.og.test",
                    "role": "student",
                    "first_name": name,
                    "last_name": surname,
                    "middle_name": "Сергеевич",
                }
            )
    result.extend(
        [
            {
                "email": "teacher.outside@demo.og.test",
                "role": "teacher",
                "first_name": "Виктор",
                "last_name": "БезНазначения",
                "middle_name": "Петрович",
            },
            {
                "email": "student.outside@demo.og.test",
                "role": "student",
                "first_name": "Олег",
                "last_name": "БезКласса",
                "middle_name": "Игоревич",
            },
        ]
    )
    return result


def study_weeks_of_year() -> list[list[date]]:
    """All study weeks of the school calendar (Monday-based lists).

    The calendar module is the single source of school dates: the weeks
    come from study_weeks of tools/demo_year_plan.py over its school
    days, so vacations never produce a week and every day is a real
    school day.
    """
    from demo_year_plan import study_weeks

    return study_weeks(school_calendar.school_days())


def current_study_week(today: date | None = None) -> list[date]:
    """Returns the school days of the current study week.

    The Monday-based week of today counts as the current study week
    while it still holds a school day that is not in the past (a Sunday
    after a study week therefore moves to the next one, so scenarios
    land on lessons that are still ahead). When the week of today holds
    no school day at all (a vacation week, a date outside the study
    year) the nearest following study week is returned; past the end of
    the year the last study week is returned, so scenarios always land
    on real school days.
    """
    today = datetime.now(TIMEZONE).date() if today is None else today
    weeks = study_weeks_of_year()
    monday = today - timedelta(days=today.weekday())
    for week in weeks:
        if week[0] == monday:
            if any(day >= today for day in week):
                return list(week)
            break
    for week in weeks:
        if week[0] > monday:
            return list(week)
    return list(weeks[-1])


def scenario_span(today: date | None = None, minimum: int = 9) -> list[date]:
    """Collects weekday study days for the scenario set of the classes.

    The span starts at the current study week and follows the calendar
    week by week (weekdays only - the small demo set keeps Saturday
    free) until at least `minimum` days are collected: the seven
    scenarios need nine lessons, seven issued plus two due targets.
    """
    today = datetime.now(TIMEZONE).date() if today is None else today
    weeks = study_weeks_of_year()
    monday = today - timedelta(days=today.weekday())
    start = len(weeks)
    for index, week in enumerate(weeks):
        if week[0] == monday:
            start = index
            break
    else:
        for index, week in enumerate(weeks):
            if week[0] > monday:
                start = index
                break
    days: list[date] = []
    for week in weeks[start:]:
        days.extend(day for day in week if day.weekday() < 5)
        if len(days) >= minimum:
            return days
    raise DemoError("Календарь не даёт достаточно учебных дней для демо-сценариев")


def choose_lesson_start(day: date, existing: list[dict]) -> datetime:
    """Выбирает первый период дня, полностью свободный для класса.

    Урок занимает точные границы периода из PERIODS (45 минут внутри
    периода, а не начало часа); существующие уроки не передвигаются.
    Пересечение с любым неотменённым уроком из existing исключается.
    """
    for period in PERIODS:
        start = datetime.combine(day, period.start_at, TIMEZONE)
        end = datetime.combine(day, period.end_at, TIMEZONE)
        if all(
            row["status"] == "canceled"
            or end <= datetime.fromisoformat(row["starts_at"])
            or start >= datetime.fromisoformat(row["ends_at"])
            for row in existing
        ):
            return start
    raise DemoError(f"Нет свободного демо-периода {day}; существующие уроки сохранены")


def ensure_user(api: Api, account: dict, existing: dict) -> dict:
    """Создаёт отсутствующую учётку; не сбрасывает пароль и роль существующей."""
    user = existing.get(account["email"])
    if user is not None:
        if user["role"] != account["role"] or not user["is_active"]:
            raise DemoError(
                f"Демо-email занят другой ролью/выключенной учёткой: {account['email']}"
            )
        return user
    user = api.request(
        "POST",
        "/internal/backoffice/users",
        {**account, "password": DEMO_PASSWORD},
        ok=(201,),
    )
    existing[account["email"]] = user
    return user


def load_apis() -> tuple[Api, Api, Api, Api]:
    """Читает только локальную конфигурацию Compose, оставляя секреты в памяти."""
    # На сервере поверх dev-настроек действует публичный override (домен и
    # https-Origin); без него вход через портал получает отказ 403.
    # Маркер сервера — каталог релизов: локально override в репозитории
    # есть, но локальный стек работает на dev-настройках.
    compose_files = ["compose.yaml", "compose.dev.yaml"]
    if (
        Path("/opt/online-gymnasium-releases").is_dir()
        and (ROOT / "deploy" / "public" / "compose.public.yaml").exists()
    ):
        compose_files.append("deploy/public/compose.public.yaml")
    result = subprocess.run(
        [
            "docker",
            "compose",
            *[arg for name in compose_files for arg in ("-f", name)],
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise DemoError(
            "Не удалось прочитать конфигурацию Compose; проверьте env-файлы"
        )
    services = json.loads(result.stdout)["services"]
    gateway = services["gateway-api"]["environment"]
    journal = services["journal-api"]["environment"]

    def base(service, target):
        ports = [p for p in services[service].get("ports", []) if p["target"] == target]
        if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1":
            raise DemoError(f"Ожидался локальный опубликованный порт {service}")
        return f"http://127.0.0.1:{ports[0]['published']}"

    return (
        Api(
            base("gateway-api", 8000),
            {"X-Backoffice-Service-Token": gateway["BACKOFFICE_SERVICE_TOKEN"]},
        ),
        Api(
            base("journal-api", 8000),
            {
                "Authorization": "Bearer " + journal["BACKOFFICE_SERVICE_TOKEN"],
                "X-Actor-ID": "1",
            },
        ),
        Api(
            base("schedule-api", 8000),
            {"Authorization": "Bearer " + gateway["SCHEDULE_SERVICE_TOKEN"]},
        ),
        Api(base("web", 80), {"Origin": gateway["PUBLIC_ORIGIN"]}),
    )


def login(public: Api, email: str) -> Api:
    """Получает собственный access-токен демо-пользователя обычным входом."""
    result = public.request(
        "POST", "/api/v1/auth/login", {"email": email, "password": DEMO_PASSWORD}
    )
    session = Api(
        public.base,
        {**public.headers, "Authorization": "Bearer " + result["access_token"]},
    )
    cookies = SimpleCookie()
    cookies.load(public.last_cookie)
    if "refresh_token" in cookies:
        session.session_cookie = "refresh_token=" + cookies["refresh_token"].value
        SESSIONS.append(session)
    return session


def close_demo_sessions() -> None:
    """Отзывает только refresh-сессии, открытые этим запуском наполнения."""
    while SESSIONS:
        session = SESSIONS.pop()
        try:
            session.request(
                "POST",
                "/api/v1/auth/logout",
                ok=(204,),
                headers={"Cookie": session.session_cookie},
            )
        except DemoError:
            print(
                "Предупреждение: отзыв одной из демо-сессий не подтверждён",
                file=sys.stderr,
            )


def demo_png() -> bytes:
    """Создаёт настоящий PNG 8×8 для загрузки и проверки скачанных байтов."""

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 8, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x22\x99\x88" * 8) * 8))
        + chunk(b"IEND", b"")
    )


def file_input() -> dict:
    """Описывает одни и те же проверяемые байты демонстрационного изображения."""
    data = demo_png()
    return {
        "file_name": "demo-example.png",
        "size_bytes": len(data),
        "content_type": "image/png",
        "content_sha256": hashlib.sha256(data).hexdigest(),
    }


def upload_file(api: Api, path: str, file: dict) -> None:
    """Догружает только pending-файл и проверяет содержимое приватного скачивания."""
    if file["upload_status"] == "pending":
        boundary = "og-demo-file-boundary"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="demo-example.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
        body += demo_png() + f"\r\n--{boundary}--\r\n".encode()
        api.request(
            "PUT",
            path,
            body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    if api.request("GET", path) != demo_png():
        raise DemoError("Скачанное демо-вложение отличается от отправленного")


def ensure_lessons(
    schedule: Api, teacher: Api, teacher_id: str, class_id: int, days: list[date]
) -> list[dict]:
    """Добавляет по уроку в день, повторно используя свои существующие занятия.

    Свои уроки ищутся по классу и дню независимо от предмета: смена набора
    предметов сценария не должна плодить вторые уроки одного дня. Новые
    уроки циклически проходят несколько предметов, чтобы демо-сценарии
    не накапливали к неделе пять часов русского или математики.
    """
    own = []
    for first in (days[0], days[5]):
        query = urlencode(
            {
                "date_from": first.isoformat(),
                "date_to": (first + timedelta(days=4)).isoformat(),
            }
        )
        own.extend(teacher.request("GET", "/api/v1/lessons?" + query))
    scenario_subjects = (1, 1001, 2, 1003)
    result = []
    for index, day in enumerate(days):
        subject = scenario_subjects[index % len(scenario_subjects)]
        found = [
            row
            for row in own
            if row["class_id"] == class_id
            and datetime.fromisoformat(row["starts_at"]).astimezone(TIMEZONE).date()
            == day
        ]
        if found:
            result.append(found[0])
            continue
        query = urlencode({"class_id": class_id, "date": day.isoformat()})
        existing = schedule.request("GET", "/lessons?" + query)
        # Слот должен быть свободен и у класса, и у самого учителя:
        # в большой школе предметники загружены до вечера (иначе API даст 409).
        own_day = [
            row
            for row in own
            if datetime.fromisoformat(row["starts_at"]).astimezone(TIMEZONE).date()
            == day
        ]
        start = choose_lesson_start(day, existing + own_day)
        body = {
            "class_id": class_id,
            "teacher_id": teacher_id,
            "subject_id": subject,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(minutes=45)).isoformat(),
        }
        # В ключ входят слот и тело: повтор после неизвестного сетевого исхода безопасен.
        key = (
            "demo-school-"
            + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        )
        result.append(
            schedule.request(
                "POST",
                "/lessons",
                body,
                ok=(200, 201),
                headers={"Idempotency-Key": key},
            )
        )
    return result


def ensure_homework(
    teacher: Api,
    lessons: list[dict],
    index: int,
    *,
    due_lesson: dict | str | None = "auto",
) -> tuple[dict, bool]:
    """Не изменяет существующее задание; создаёт недостающий демонстрационный пример.

    due_lesson переопределяет цель срока: словарь урока — срок-урок,
    None — ручной срок, "auto" (по умолчанию) — прежнее поведение
    сценариев 0 и 6 (уроки 6 и 8 набора).
    """
    lesson = lessons[index]
    card = teacher.request("GET", f"/api/v1/lessons/{lesson['id']}")
    found = card["homework_from_lesson"]
    if found:
        return found[0], False
    body = {
        "description": f"[ДЕМО] {LABELS[index]}. Прочитайте условие и объясните решение.",
        "files": [],
    }
    target = due_lesson
    if target == "auto":
        target = lessons[6 if index == 0 else 8]["id"] if index in (0, 6) else None
    if isinstance(target, dict):
        body["due_lesson_id"] = target["id"]
    elif isinstance(target, int):
        body["due_lesson_id"] = target
    else:
        # Стабильный срок относительно недели, а не новый timestamp каждого повтора.
        start = datetime.fromisoformat(lessons[-1]["ends_at"])
        body["manual_due_datetime"] = (start + timedelta(days=3)).isoformat()
    if index == 5:
        body["files"] = [file_input()]
    return teacher.request(
        "POST", f"/api/v1/lessons/{lesson['id']}/homework", body, ok=(201,)
    ), True


def ensure_answer(
    student: Api, homework: dict, key: str, text: str, with_file=False
) -> tuple[dict, bool]:
    """Читает ключ-повтор; новая попытка не создаётся вместо изменённой пользователем."""
    body = {"answer_text": text, "files": [file_input()] if with_file else []}
    # Используется только для заранее определённых попыток; API сверяет хеш тела.
    answer = student.request(
        "POST",
        f"/api/v1/homework/{homework['id']}/answers",
        body,
        ok=(200, 201),
        headers={"Idempotency-Key": key},
    )
    return answer, answer["status"] == "submitted"


def prepare_answers(
    session_of, students: list[Api], homework: list[dict], new: list[bool]
) -> None:
    """Наполняет только ещё не начатые сценарии, не перезаписывая ручную проверку.

    session_of(index) возвращает сеанс автора сценария: в маленькой
    школе это один учитель, в большой — преподаватель каждого урока.
    """
    # Если ответов ещё нет после прерванного запуска, можно безопасно продолжить.
    for index in range(1, 6):
        task = homework[index]
        teacher = session_of(index)
        answers = teacher.request("GET", f"/api/v1/homework/{task['id']}/answers")
        if answers and not new[index]:
            continue
        student = students[min(index, 4)] if index < 5 else students[0]
        prefix = f"demo-school-{task['id']}"
        answer, submitted = ensure_answer(
            student,
            task,
            prefix + "-first",
            "Демонстрационный ответ: решение и объяснение.",
            index == 5,
        )
        path = f"/api/v1/homework/{task['id']}/answers/{answer['id']}"
        if index == 5:
            upload_file(
                student, path + f"/files/{answer['files'][0]['id']}", answer["files"][0]
            )
            ensure_answer(
                students[1],
                task,
                prefix + "-pending-file",
                "Пример: ответ сохранён, файл пока не загружен.",
                True,
            )
        elif submitted and index in (2, 3, 4):
            decision = {
                "status": "graded" if index == 4 else "returned",
                "grade": 4 if index == 4 else None,
                "teacher_comment": "Хорошая работа!"
                if index == 4
                else "Добавьте подробное объяснение решения.",
            }
            teacher.request("PUT", path + "/review", decision)
            if index == 3:
                ensure_answer(
                    student,
                    task,
                    prefix + "-second",
                    "Исправленный ответ: добавлено объяснение каждого шага.",
                )


def verify_school(
    public: Api, classes: list[dict], users: dict, days: list[date]
) -> None:
    """Проверяет публичные чтения, чужой доступ и готовые файлы без изменения работ."""
    student = login(public, "student01.1@demo.og.test")
    tasks = student.request("GET", "/api/v1/homework")
    own = [row for row in tasks if row["class_id"] == classes[0]["id"]]
    if len(own) < 7:
        raise DemoError("У ученика 1А отсутствуют ожидаемые демонстрационные ДЗ")
    task = own[0]
    login(public, "student02.1@demo.og.test").request(
        "GET", f"/api/v1/homework/{task['id']}", ok=(404,)
    )
    login(public, "student.outside@demo.og.test").request(
        "GET", f"/api/v1/homework/{task['id']}", ok=(404,)
    )
    login(public, "teacher.outside@demo.og.test").request(
        "GET", f"/api/v1/lessons/{task['issued_lesson_id']}", ok=(403,)
    )
    print(
        "Проверены публичный список ДЗ и запреты для чужого класса/ученика/учителя.",
        flush=True,
    )


# ------------------------------------------------------------------
# Year scenarios on the current study week (spec section 7)


def class_week_lessons(schedule: Api, class_id: int, days: list[date]) -> list[dict]:
    """Planned lessons of the class inside the day window, time-sorted.

    The lessons endpoint takes a single calendar date, so the window is
    fetched one day at a time and merged.
    """
    rows: list[dict] = []
    for day in days:
        query = urlencode({"class_id": class_id, "date": day.isoformat()})
        rows.extend(schedule.request("GET", "/lessons?" + query))
    return sorted(
        (row for row in rows if row["status"] == "planned"),
        key=lambda row: (row["starts_at"], row["id"]),
    )


def choose_scenario_lessons(
    rows: list[dict], extra_rows: list[dict], now: datetime
) -> tuple[list[dict], dict | None]:
    """Picks the issued lessons and the lesson deadline of the scenarios.

    Slots 0-6 issue the seven scenarios on the earliest planned lessons
    of the current study week (one homework per lesson). Scenario 0
    needs a later future lesson of the same subject as its deadline;
    extra_rows extends the search into the following study week. A None
    deadline means the manual deadline of the default mechanism.
    """
    if len(rows) < 7:
        raise DemoError(
            "На текущей учебной неделе меньше семи уроков класса для сценариев ДЗ"
        )
    issued = rows[:7]
    first_start = datetime.fromisoformat(issued[0]["starts_at"])
    deadline = None
    for row in rows[1:] + list(extra_rows):
        start = datetime.fromisoformat(row["starts_at"])
        if (
            row["subject_id"] == issued[0]["subject_id"]
            and start > first_start
            and start > now
        ):
            deadline = row
            break
    return issued, deadline


def future_school_days(after: date, count: int = 14) -> list[date]:
    """Returns the first school days of the calendar after the date."""
    return [day for day in school_calendar.school_days() if day > after][:count]


def create_deadline_lesson(
    schedule: Api, class_id: int, subject_id: int, teacher_id: str, after: date
) -> dict:
    """Creates one extra planned lesson as the canceled-deadline target.

    The lesson repeats the subject of the showcase scenario on the
    first free period of the next school days. It is canceled right
    after the homework creation (the "срок привязан к отменённому
    уроку" showcase), so the idempotent replay of an already canceled
    slot moves the next attempt to another period.
    """
    taken: list[dict] = []
    for day in future_school_days(after):
        query = urlencode({"class_id": class_id, "date": day.isoformat()})
        class_lessons = schedule.request("GET", "/lessons?" + query)
        teacher_day = schedule.request(
            "GET",
            "/internal/teacher-lessons?"
            + urlencode({"date_from": day.isoformat(), "date_to": day.isoformat()}),
            headers={"X-Teacher-ID": teacher_id},
        )
        blocked = [
            {**row, "status": "planned"} if row["status"] == "canceled" else row
            for row in class_lessons + teacher_day
        ] + [dict(row, status="planned") for row in taken]
        try:
            start = choose_lesson_start(day, blocked)
        except DemoError:
            continue
        body = {
            "class_id": class_id,
            "teacher_id": teacher_id,
            "subject_id": subject_id,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(minutes=45)).isoformat(),
        }
        key = (
            "demo-school-"
            + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        )
        lesson = schedule.request(
            "POST",
            "/lessons",
            body,
            ok=(200, 201),
            headers={"Idempotency-Key": key},
        )
        if lesson["status"] == "planned":
            return lesson
        taken.append(lesson)
    raise DemoError(
        "Не нашлось свободного периода для урока-срока сценария отменённого дедлайна"
    )


def create_year_scenarios(
    gateway: Api,
    journal: Api,
    schedule: Api,
    public: Api,
    users: dict,
    summary: list[dict],
    *,
    today: date | None = None,
) -> None:
    """Recreates the demo homework scenarios on the current study week.

    The showcase classes are the documented "А" lines (teacher01..
    teacher11 are their class teachers). Seven homework per class are
    issued on the lessons of the current study week of the year plan -
    one homework per lesson, the author is the lesson teacher of the
    plan - with the prepared answers on top (the existing idempotency
    mechanism: found homework and answer keys are reused on repeats).
    The canceled-deadline showcase points at a freshly created
    demo-school lesson; year-plan lessons themselves are never
    canceled, so the year verification of the next run stays green.
    """
    today = datetime.now(TIMEZONE).date() if today is None else today
    now = datetime.combine(today, datetime.now(TIMEZONE).time(), TIMEZONE)
    week = current_study_week(today)
    weeks = study_weeks_of_year()
    index = next(i for i, item in enumerate(weeks) if item[0] == week[0])
    next_week = weeks[index + 1] if index + 1 < len(weeks) else []
    email_by_id = {user["id"]: email for email, user in users.items()}
    sessions: dict[str, Api] = {}

    def teacher_session(teacher_id: str) -> Api:
        email = email_by_id.get(teacher_id)
        if email is None:
            raise DemoError(f"Урок ведёт не демо-учитель: {teacher_id}")
        if email not in sessions:
            sessions[email] = login(public, email)
        return sessions[email]

    for row in summary:
        if not row["name"].endswith("А"):
            continue
        class_id = row["id"]
        rows = class_week_lessons(schedule, class_id, week)
        extra_rows = class_week_lessons(schedule, class_id, next_week)
        issued, deadline = choose_scenario_lessons(rows, extra_rows, now)
        target = create_deadline_lesson(
            schedule,
            class_id,
            issued[6]["subject_id"],
            issued[6]["teacher_id"],
            datetime.fromisoformat(issued[6]["starts_at"]).astimezone(TIMEZONE).date(),
        )
        lessons = [*issued, target]
        prepared = []
        for scenario in range(7):
            due = deadline if scenario == 0 else (target if scenario == 6 else "auto")
            prepared.append(
                ensure_homework(
                    teacher_session(issued[scenario]["teacher_id"]),
                    lessons,
                    scenario,
                    due_lesson=due,
                )
            )
        homework, created = (
            [part[0] for part in prepared],
            [part[1] for part in prepared],
        )
        file_task = homework[5]
        if (
            file_task["files"]
            and file_task["files"][0]["file_name"] == "demo-example.png"
        ):
            upload_file(
                teacher_session(issued[5]["teacher_id"]),
                f"/api/v1/homework/{file_task['id']}/files/{file_task['files'][0]['id']}",
                file_task["files"][0],
            )
        students = [login(public, email) for email in row["students"][:5]]
        authors = [lesson_row["teacher_id"] for lesson_row in issued]
        prepare_answers(
            lambda scenario, authors=authors: teacher_session(authors[scenario]),
            students,
            homework,
            created,
        )
        if target["status"] == "planned":
            schedule.request(
                "POST",
                f"/lessons/{target['id']}/cancel",
                {"expected_version": target["version"]},
            )
        print(
            f"{row['name']}: 7 сценариев ДЗ и ответы на текущей учебной неделе "
            f"({week[0]} — {week[-1]}).",
            flush=True,
        )


def main() -> None:
    """Проверяет локальные API и по явному --apply создаёт согласованный демо-набор."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Добавить недостающие демонстрационные записи",
    )
    parser.add_argument(
        "--large", action="store_true", help="Большая школа: классы 1–11 А–Д"
    )
    args = parser.parse_args()
    gateway, journal, schedule, public = load_apis()
    for api in (gateway, journal, schedule):
        api.request("GET", "/health/live")
    accounts = build_accounts()
    # Единственный источник дат — школьный календарь домена Schedule.
    week = current_study_week()
    days = scenario_span()
    study_year = school_calendar.STUDY_YEAR[0].year
    if args.large:
        from expand_demo_school import apply_expansion, expansion_accounts

        print(
            f"План: 55 классов, {len(expansion_accounts())} демо-учёток, "
            f"полный учебный год {school_calendar.STUDY_YEAR[0].year}/"
            f"{school_calendar.STUDY_YEAR[1].year % 100:02d} по календарю; "
            f"текущая учебная неделя {week[0]} — {week[-1]}.",
            flush=True,
        )
        if not args.apply:
            print("API доступны. Для записи добавьте --apply. Ничего не изменено.")
            return
        from rebuild_demo_timetable import (
            rebuild_year,
            wipe_year_lessons,
            year_rebuild_due,
        )

        if year_rebuild_due():
            # Старые уроки ведут учителей, которых новая сетка предметов
            # больше не разрешает: чистим их до настройки справочника.
            print(
                "Отпечаток года не совпал: очистка старых уроков до expand.",
                flush=True,
            )
            wiped = wipe_year_lessons(journal, study_year)
            print(f"Очистка до expand: {wiped}", flush=True)
        summary = apply_expansion(gateway, journal, schedule, study_year)
        users = {
            u["email"]: u for u in gateway.request("GET", "/internal/backoffice/users")
        }
        classes = [{"id": row["id"], "name": row["name"]} for row in summary]

        rebuild_year(journal, classes, users)
        create_year_scenarios(gateway, journal, schedule, public, users, summary)
        print(
            f"Готово: {len(summary)} классов. Список: .demo-data/expanded-school.json"
        )
        return
    print(
        f"План: классы 1А–11А, {len(accounts)} учёток, {len(days) * 11} уроков, "
        f"77 ДЗ; {days[0]} — {days[-1]}.",
        flush=True,
    )
    if not args.apply:
        print("API доступны. Для записи повторите с --apply. Ничего не изменено.")
        return
    users = {
        u["email"]: u for u in gateway.request("GET", "/internal/backoffice/users")
    }
    for account in accounts:
        ensure_user(gateway, account, users)
    print(
        "Демо-пользователи готовы; существующие пароли и профили сохранены.", flush=True
    )
    from expand_demo_school import expansion_accounts

    demo_teachers = {
        account["email"]
        for account in [*accounts, *expansion_accounts()]
        if account["role"] == "teacher"
    }
    subject_names = {
        "subjects": [
            {"id": 1, "name": "Математика"},
            {"id": 2, "name": "Русский язык"},
        ],
        "allowed_teacher_ids": [
            user["id"] for email, user in users.items() if email in demo_teachers
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
        input=json.dumps(subject_names),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise DemoError(
            "Не удалось подтвердить названия демо-предметов. Проверьте миграции/образ Schedule; существующие названия не перезаписываются."
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
    report_classes = []
    for grade in range(1, 12):
        name = f"{grade}А"
        school_class = next((row for row in existing if row["name"] == name), None)
        if school_class is None:
            school_class = journal.request(
                "POST",
                "/internal/classes",
                {"name": name, "study_year": study_year},
                ok=(201,),
            )
        class_id = school_class["id"]
        teacher_user = users[f"teacher{grade:02}@demo.og.test"]
        journal.request(
            "PUT",
            f"/internal/teachers/{teacher_user['id']}/classes/{class_id}",
            ok=(201, 204),
        )
        for index in range(1, 6):
            user = users[f"student{grade:02}.{index}@demo.og.test"]
            journal.request(
                "PUT",
                f"/internal/students/{user['id']}/current-class-period",
                {"class_id": class_id},
                ok=(200, 201),
            )
        parent = users[f"parent{grade:02}@demo.og.test"]
        child = users[f"student{grade:02}.1@demo.og.test"]
        gateway.request(
            "PUT",
            f"/internal/backoffice/parents/{parent['id']}/children/{child['id']}",
            ok=(201, 204),
        )
        teacher = login(public, teacher_user["email"])
        lessons = ensure_lessons(schedule, teacher, teacher_user["id"], class_id, days)
        prepared = [ensure_homework(teacher, lessons, index) for index in range(7)]
        homework, created = [p[0] for p in prepared], [p[1] for p in prepared]
        file_task = homework[5]
        if (
            file_task["files"]
            and file_task["files"][0]["file_name"] == "demo-example.png"
        ):
            upload_file(
                teacher,
                f"/api/v1/homework/{file_task['id']}/files/{file_task['files'][0]['id']}",
                file_task["files"][0],
            )
        students = [
            login(public, f"student{grade:02}.{index}@demo.og.test")
            for index in range(1, 6)
        ]
        prepare_answers(teacher, students, homework, created)
        # Отмена только нового собственного примера, не ручных изменений пользователя.
        if created[6] and lessons[8]["status"] == "planned":
            schedule.request(
                "POST",
                f"/lessons/{lessons[8]['id']}/cancel",
                {"expected_version": lessons[8]["version"]},
            )
        report_classes.append(
            {
                "id": class_id,
                "name": name,
                "teacher_email": teacher_user["email"],
                "student_emails": [
                    f"student{grade:02}.{index}@demo.og.test" for index in range(1, 6)
                ],
                "parent_email": parent["email"],
                "lesson_ids": [row["id"] for row in lessons],
                "homework": [
                    {
                        "id": row["id"],
                        "scenario": LABELS[i],
                        "lesson_id": row["issued_lesson_id"],
                        "student_url": f"http://localhost:8080/homework/{row['id']}",
                        "teacher_url": f"http://localhost:8080/lessons/{row['issued_lesson_id']}",
                    }
                    for i, row in enumerate(homework)
                ],
            }
        )
        print(
            f"{name}: 5 учеников, преподаватель, родитель, 10 уроков и 7 примеров ДЗ готовы.",
            flush=True,
        )
    verify_school(public, report_classes, users, days)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.with_name("demo-example.png").write_bytes(demo_png())
    REPORT.write_text(
        json.dumps(
            {
                "created_at": datetime.now(TIMEZONE).isoformat(),
                "dates": [str(days[0]), str(days[-1])],
                "demo_password": DEMO_PASSWORD,
                "accounts": [
                    {
                        "email": a["email"],
                        "role": a["role"],
                        "id": users[a["email"]]["id"],
                        "name": " ".join(
                            a[k] for k in ("last_name", "first_name", "middle_name")
                        ),
                    }
                    for a in accounts
                ],
                "classes": report_classes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        f"Готово. Логины, ID, сценарии: {REPORT.relative_to(ROOT)}. Пароль демо-учёток: {DEMO_PASSWORD}"
    )
    lines = [
        "# Демонстрационная школа OG",
        "",
        f"Расписание: {days[0]} — {days[-1]}, часовой пояс Asia/Yekaterinburg.",
        "",
        "Только для локальных ручных проверок. Это не реальные ученики и не данные для публикации.",
        "",
        f"Пароль всех демо-учёток: `{DEMO_PASSWORD}`. Настоящие пользователи не изменялись.",
        "",
        "## Быстрый старт",
        "",
        "Учитель 1А: `teacher01@demo.og.test`. Ученики: `student01.1@demo.og.test` — `student01.5@demo.og.test`.",
        "Для других классов замените 01 на номер класса с ведущим нулём: 02, 03, …, 11.",
        "",
        "Родитель: `parent01@demo.og.test`, связан с первым учеником. Родительский кабинет не заменяет ученический.",
        "",
        "Чужие права: `teacher.outside@demo.og.test` не имеет назначений; `student.outside@demo.og.test` не состоит в классе.",
        "",
        "В каждом классе семь заданий. Ответы заранее подготовлены только для указанных учеников; остальные могут сдавать самостоятельно.",
        "",
        "| Сценарий | Ученик |",
        "|---|---|",
        "| Нет ответа | Первый ученик; первое ДЗ |",
        "| Ожидает проверки | Второй ученик; второе ДЗ |",
        "| Возвращено | Третий ученик; третье ДЗ |",
        "| Повторная попытка | Четвёртый ученик; четвёртое ДЗ |",
        "| Оценка 4 | Пятый ученик; пятое ДЗ |",
        "| Файлы | Шестое ДЗ: первый ученик — готовый файл, второй — pending |",
        "| Отменён срок-урок | Седьмое ДЗ |",
        "",
        "Для догрузки pending-файла выберите находящийся рядом `demo-example.png`. Его имя и содержимое соответствуют сохранённым метаданным.",
        "",
        "## Ссылки на задания",
        "",
    ]
    for school_class in report_classes:
        lines.extend([f"### {school_class['name']}", ""])
        for task in school_class["homework"]:
            lines.append(
                f"- {task['scenario']}: [ученик]({task['student_url']}), [учитель]({task['teacher_url']})."
            )
        lines.append("")
    lines.extend(["## Все учётки", "", "| ФИО | Роль | Email |", "|---|---|---|"])
    for account in accounts:
        name = " ".join(account[k] for k in ("last_name", "first_name", "middle_name"))
        lines.append(f"| {name} | {account['role']} | `{account['email']}` |")
    lines.extend(
        [
            "",
            "## Повторный запуск",
            "",
            "`python3 tools/create_demo_data.py --apply`",
            "",
            "Добавляет недостающие записи; не очищает базы и не сбрасывает пароли существующих учёток. Ручные решения преподавателя сохраняются.",
            "При ручном переводе демо-ученика в другой класс скрипт остановится на конфликте, а не переведёт его обратно.",
            "",
        ]
    )
    REPORT.with_name("README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    atexit.register(close_demo_sessions)
    try:
        main()
    except (DemoError, KeyError, ValueError) as exc:
        print(f"Остановлено: {exc}", file=sys.stderr)
        sys.exit(1)
