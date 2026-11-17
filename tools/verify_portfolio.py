"""Проверяет основные чтения демо-портала без создания учебных данных.

Запуск из корня: poetry -C services/gateway run python ../../tools/verify_portfolio.py
"""

import json
from datetime import date, datetime
from pathlib import Path

from create_demo_data import TIMEZONE, DemoError, close_demo_sessions, load_apis, login


def main() -> None:
    """Проверяет роли, домашние задания и доступ к связанным разделам."""
    _, _, _, public = load_apis()
    try:
        student = login(public, "student01.1@demo.og.test")
        teacher = login(public, "teacher01@demo.og.test")
        parent = login(public, "parent01@demo.og.test")
        admin = login(public, "admin@demo.og.test")

        for expected_role, session in (
            ("student", student),
            ("teacher", teacher),
            ("parent", parent),
            ("admin", admin),
        ):
            if session.request("GET", "/api/v1/auth/me")["role"] != expected_role:
                raise DemoError(f"Неверная роль: {expected_role}")
        print("Вход и роли: ученик, преподаватель, родитель, администратор — OK")

        homework = student.request("GET", "/api/v1/homework")
        if not homework:
            raise DemoError("У демо-ученика нет заданий")
        student.request("GET", f"/api/v1/homework/{homework[0]['id']}")
        teacher.request("GET", f"/api/v1/lessons/{homework[0]['issued_lesson_id']}")
        student.request("GET", "/api/v1/analytics/classes", ok=(403,))
        print("ДЗ ученика, карточка преподавателя и запрет аналитики ученику — OK")

        children = parent.request("GET", "/api/v1/billing/students")
        if not children:
            raise DemoError("У демо-родителя нет связанного ученика")
        admin.request("GET", "/api/v1/analytics/classes")
        admin.request("GET", "/api/v1/billing/payments")
        admin.request("GET", "/api/v1/documents")
        student.request("GET", "/api/v1/notifications/count")
        print("Связь родителя, аналитика, платежи, документы и уведомления — OK")

        report = Path(__file__).resolve().parents[1] / ".demo-data" / "report.json"
        if report.exists():
            dates = json.loads(report.read_text())["dates"]
            last_day = date.fromisoformat(dates[-1])
            if last_day < datetime.now(TIMEZONE).date():
                print(
                    f"Расписание демо заканчивается {last_day}: нужны актуальные уроки."
                )
            else:
                schedule = student.request(
                    "GET", f"/api/v1/my-schedule?week_start={dates[0]}"
                )
                if not any(day["lessons"] for day in schedule["days"]):
                    raise DemoError("В актуальной демо-неделе нет уроков ученика")
                print("Актуальное недельное расписание ученика — OK")
    finally:
        close_demo_sessions()


if __name__ == "__main__":
    main()
