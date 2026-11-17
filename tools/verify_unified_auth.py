"""Проверяет общий вход и выход на локальном демо без изменения пользователей."""

import httpx
from create_demo_data import DEMO_PASSWORD

ORIGIN = "http://localhost:8080"


def start_session(client: httpx.Client) -> str:
    """Входит под демо-администратором и открывает связанную админку."""
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@demo.og.test", "password": DEMO_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    login.raise_for_status()
    access_token = login.json()["access_token"]
    client.get("/admin/sso/csrf/").raise_for_status()
    csrf_token = client.cookies["csrftoken"]
    bridge = client.post(
        "/admin/sso/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-CSRFToken": csrf_token,
            "Origin": ORIGIN,
        },
    )
    bridge.raise_for_status()
    assert bridge.status_code == 204
    admin = client.get("/admin/")
    assert admin.status_code == 200 and "Общий вход" in admin.text
    return access_token


def main() -> None:
    """Проверяет отзыв общей сессии в обоих направлениях."""
    with httpx.Client(base_url=ORIGIN, timeout=10.0, follow_redirects=False) as client:
        access = start_session(client)
        csrf_token = client.cookies["csrftoken"]
        result = client.post(
            "/admin/logout/", headers={"X-CSRFToken": csrf_token, "Origin": ORIGIN}
        )
        assert result.status_code == 302
        assert (
            client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
            ).status_code
            == 401
        )
        assert (
            client.post("/api/v1/auth/refresh", headers={"Origin": ORIGIN}).status_code
            == 401
        )
        print("Выход из Backoffice отзывает сессию Gateway: OK")

    with httpx.Client(base_url=ORIGIN, timeout=10.0, follow_redirects=False) as client:
        start_session(client)
        assert (
            client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code
            == 204
        )
        assert client.get("/admin/").status_code == 401
        print("Выход из портала закрывает доступ к Backoffice: OK")

    with httpx.Client(base_url=ORIGIN, timeout=10.0, follow_redirects=False) as client:
        start_session(client)
        try:
            failed = client.post(
                "/api/v1/auth/login",
                json={
                    "email": "student01.1@demo.og.test",
                    "password": "wrong-test-password",
                },
                headers={"Origin": ORIGIN},
            )
            assert failed.status_code == 401
            assert client.get("/admin/").status_code == 200
            result = client.post(
                "/api/v1/auth/login",
                json={"email": "student01.1@demo.og.test", "password": DEMO_PASSWORD},
                headers={"Origin": ORIGIN},
            )
            assert result.status_code == 200
            assert client.get("/admin/").status_code == 401
            print("Вход ученика закрывает предыдущую админскую сессию: OK")
        finally:
            client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})


if __name__ == "__main__":
    main()
