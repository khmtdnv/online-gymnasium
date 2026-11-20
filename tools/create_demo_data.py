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
import zlib
from datetime import date, datetime, time, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TIMEZONE = ZoneInfo("Asia/Yekaterinburg")
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
            if status not in ok:
                # Не печатаем запросы, токены, пароли или чужие ответы сервиса.
                raise DemoError(f"{method} {path}: HTTP {status}")
            if status == 404 or not content:
                return None
            if "json" in response.headers.get("Content-Type", ""):
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


def school_days(today: date) -> list[date]:
    """Возвращает десять будних дней текущей и следующей календарных недель."""
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=offset) for offset in range(12) if offset % 7 < 5]


def choose_lesson_start(day: date, existing: list[dict]) -> datetime:
    """Выбирает свободные 45 минут класса, не передвигая существующие уроки."""
    for hour in range(9, 20):
        start = datetime.combine(day, time(hour), TIMEZONE)
        end = start + timedelta(minutes=45)
        if all(
            row["status"] == "canceled"
            or end <= datetime.fromisoformat(row["starts_at"])
            or start >= datetime.fromisoformat(row["ends_at"])
            for row in existing
        ):
            return start
    raise DemoError(
        f"Нет свободного демо-интервала {day}; существующие уроки сохранены"
    )


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
    compose_files = ["compose.yaml", "compose.dev.yaml"]
    if (ROOT / "deploy" / "public" / "compose.public.yaml").exists():
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
    """Добавляет по уроку в день, повторно используя свои существующие занятия."""
    own = []
    for first in (days[0], days[5]):
        query = urlencode(
            {
                "date_from": first.isoformat(),
                "date_to": (first + timedelta(days=4)).isoformat(),
            }
        )
        own.extend(teacher.request("GET", "/api/v1/lessons?" + query))
    result = []
    for index, day in enumerate(days):
        subject = 1 + index % 2
        found = [
            row
            for row in own
            if row["class_id"] == class_id
            and row["subject_id"] == subject
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


def ensure_homework(teacher: Api, lessons: list[dict], index: int) -> tuple[dict, bool]:
    """Не изменяет существующее задание; создаёт недостающий демонстрационный пример."""
    lesson = lessons[index]
    card = teacher.request("GET", f"/api/v1/lessons/{lesson['id']}")
    found = card["homework_from_lesson"]
    if found:
        return found[0], False
    body = {
        "description": f"[ДЕМО] {LABELS[index]}. Прочитайте условие и объясните решение.",
        "files": [],
    }
    if index in (0, 6):
        body["due_lesson_id"] = lessons[6 if index == 0 else 8]["id"]
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
    teacher: Api, students: list[Api], homework: list[dict], new: list[bool]
) -> None:
    """Наполняет только ещё не начатые сценарии, не перезаписывая ручную проверку."""
    # Если ответов ещё нет после прерванного запуска, можно безопасно продолжить.
    for index in range(1, 6):
        task = homework[index]
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
    days = school_days(datetime.now(TIMEZONE).date())
    study_year = days[0].year if days[0].month >= 9 else days[0].year - 1
    if args.large:
        from expand_demo_school import apply_expansion, expansion_accounts

        print(
            f"План: 55 классов, {len(expansion_accounts())} демо-учёток, "
            f"по 5–6 уроков в день; {days[0]} — {days[-1]}.",
            flush=True,
        )
        if not args.apply:
            print("API доступны. Для записи добавьте --apply. Ничего не изменено.")
            return
        summary = apply_expansion(gateway, journal, schedule, days, study_year)
        print(
            f"Готово: {len(summary)} классов. Список: .demo-data/expanded-school.json"
        )
        return
    print(
        f"План: классы 1А–11А, {len(accounts)} учёток, 110 уроков, 77 ДЗ; {days[0]} — {days[-1]}.",
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
