"""Приводит пароли витринных демо-учёток к публичному значению портфолио.

Запускается в контейнере gateway-api (паттерн run_db из
tools/rebuild_demo_timetable.py: docker compose exec gateway-api
/app/.venv/bin/python -c <source> с JSON на stdin):

    docker compose -f compose.yaml -f deploy/public/compose.public.yaml \
        -f deploy/public/compose.release-current.yaml exec -T gateway-api \
        /app/.venv/bin/python -c "$(cat tools/reset_demo_passwords.py)" \
        <<'JSON'
    {"emails": ["teacher01@demo.og.test", "student01.1@demo.og.test",
                "parent01@demo.og.test"],
     "password": "DemoSchool2026!"}
    JSON

Политика публичного демо-доступа — решение владельца 2026-11-27
(`concepts_brief.md`): сайт online-education.fun — витрина-портфолио,
пароль демо-школы не секрет (allowlist `.gitleaks.toml`). Инструмент
меняет пароль только учёткам *@demo.og.test и отказывается трогать
роль admin: демо-админ остаётся на отдельном непубличном пароле.

Хеш вычисляет PwdlibPasswordService самого Gateway; перед фиксацией
транзакции новый хеш проверяется verify(). Прежние refresh-токены
учёток удаляются, сессии отзываются: старые креды перестают работать
сразу, а не по истечении срока.

Импорты сервиса отложены, поэтому модуль импортируется вне контейнера
для юнит-тестов.
"""

import asyncio
import json
import sys
from datetime import UTC

DEMO_DOMAIN = "@demo.og.test"


def parse_emails(raw) -> list[str]:
    """Проверяет список адресов витринных демо-учёток.

    Args:
        raw: Значение поля "emails" входного JSON.

    Returns:
        Список адресов *@demo.og.test без дубликатов, порядок сохранён.

    Raises:
        SystemExit: Значение не список, список пуст или адрес не демо-домен.
    """
    if not isinstance(raw, list) or not raw:
        raise SystemExit("Ожидается непустой список emails")
    emails = []
    for value in raw:
        if not isinstance(value, str) or not value.endswith(DEMO_DOMAIN):
            raise SystemExit(f"Не демо-email: {value!r}")
        if value not in emails:
            emails.append(value)
    return emails


def parse_password(raw) -> str:
    """Проверяет новый пароль на непустоту.

    Args:
        raw: Значение поля "password" входного JSON.

    Returns:
        Открытый пароль для вычисления хеша.

    Raises:
        SystemExit: Пароль не строка или состоит из пробелов.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise SystemExit("Пароль должен быть непустой строкой")
    return raw


async def run_reset(store_factory, password_service, session_factory, emails, password):
    """Меняет пароли и отзывает прежние сессии в одной транзакции.

    Args:
        store_factory: Создаёт SqlUserStore для открытой сессии.
        password_service: Хеширует и проверяет пароль как сам Gateway.
        session_factory: Фабрика сессий SQLAlchemy; транзакция одна.
        emails: Адреса *@demo.og.test для сброса.
        password: Новый открытый пароль демо-учёток.

    Returns:
        Отчёт: изменённые учётки, пропущенные email, счётчики отзывов.

    Raises:
        SystemExit: В списке демо-админ или хеш не прошёл самопроверку;
            транзакция откатывается целиком.
    """
    async with session_factory() as session, session.begin():
        store = store_factory(session)
        users = await store.find_users(emails)
        found = {user["email"] for user in users}
        admins = [user["email"] for user in users if user["role"] == "admin"]
        if admins:
            raise SystemExit(
                "Демо-админ не входит в публичный демо-доступ: "
                + ", ".join(sorted(admins))
            )
        password_hash = password_service.hash(password)
        if not password_service.verify(password, password_hash):
            raise SystemExit("Новый хеш не прошёл самопроверку verify()")
        changed = []
        for user in users:
            await store.update_password(user["id"], password_hash)
            tokens = await store.delete_refresh_tokens(user["id"])
            revoked = await store.revoke_sessions(user["id"])
            changed.append(
                {
                    "email": user["email"],
                    "role": user["role"],
                    "refresh_tokens_deleted": tokens,
                    "sessions_revoked": revoked,
                }
            )
    return {
        "password": password,
        "changed": changed,
        "missing": [email for email in emails if email not in found],
    }


class SqlUserStore:
    """SQL сброса паролей к одной открытой сессии.

    Строки Gateway импортируются в конструкторе: модуль остаётся
    импортируемым вне контейнера (юнит-тесты гоняют сброс на фейках).
    """

    def __init__(self, session) -> None:
        from gateway_service.infrastructure.models.auth_session import AuthSessionRow
        from gateway_service.infrastructure.models.refresh_token import (
            RefreshTokenRow,
        )
        from gateway_service.infrastructure.models.user import UserRow

        self._session = session
        self._user_row = UserRow
        self._refresh_row = RefreshTokenRow
        self._session_row = AuthSessionRow

    async def find_users(self, emails) -> list[dict]:
        """Читает id, email и роль учёток по списку адресов."""
        from sqlalchemy import select

        statement = select(
            self._user_row.id, self._user_row.email, self._user_row.role
        ).where(self._user_row.email.in_(emails))
        rows = (await self._session.execute(statement)).all()
        return [{"id": row.id, "email": row.email, "role": row.role} for row in rows]

    async def update_password(self, user_id, password_hash) -> None:
        """Записывает новый хеш пароля одной учётке."""
        from sqlalchemy import update

        await self._session.execute(
            update(self._user_row)
            .where(self._user_row.id == user_id)
            .values(password_hash=password_hash)
        )

    async def delete_refresh_tokens(self, user_id) -> int:
        """Удаляет refresh-токены учётки, чтобы старый вход не продлевался."""
        from sqlalchemy import delete

        result = await self._session.execute(
            delete(self._refresh_row).where(self._refresh_row.user_id == user_id)
        )
        return result.rowcount or 0

    async def revoke_sessions(self, user_id) -> int:
        """Отзывает ещё активные сессии учётки."""
        from datetime import datetime

        from sqlalchemy import update

        result = await self._session.execute(
            update(self._session_row)
            .where(
                self._session_row.user_id == user_id,
                self._session_row.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return result.rowcount or 0


async def main():
    from gateway_service.config import GatewaySettings
    from gateway_service.infrastructure.database import (
        create_engine,
        create_session_factory,
    )
    from gateway_service.infrastructure.password_service import PwdlibPasswordService

    data = json.load(sys.stdin)
    emails = parse_emails(data.get("emails"))
    password = parse_password(data.get("password"))
    engine = create_engine(GatewaySettings().database_url)
    sessions = create_session_factory(engine)
    try:
        result = await run_reset(
            SqlUserStore, PwdlibPasswordService(), sessions, emails, password
        )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
