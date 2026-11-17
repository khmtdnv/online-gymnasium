"""Необязательная проверка настоящего Gateway без операции у провайдера."""

import os

import httpx
import pytest
from django.test import Client, override_settings
from django.urls import reverse

from backoffice_admin.models import AdminActionRecord

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        os.getenv("BACKOFFICE_LIVE_GATEWAY") != "1",
        reason="Требуется запущенный локальный Gateway и демо-администратор",
    ),
]


def test_real_gateway_checks_admin_and_handles_disabled_payment_provider(
    django_user_model,
):
    """Проверяет сеть и отказ без магазина, используя отдельную тестовую БД Django."""
    origin = "http://localhost:8080"
    base_url = "http://127.0.0.1:8003"
    email = "admin@demo.og.test"
    password = "DemoSchool2026!"
    with httpx.Client(base_url=base_url, timeout=10) as probe:
        login = probe.post(
            "/api/v1/auth/login",
            headers={"Origin": origin},
            json={"email": email, "password": password},
        )
        login.raise_for_status()
        try:
            config = probe.get(
                "/api/v1/billing/config",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            )
            config.raise_for_status()
            if config.json()["configured"]:
                pytest.skip("Живая проверка требует выключенный платёжный магазин")
        finally:
            probe.post("/api/v1/auth/logout", headers={"Origin": origin})

    staff = django_user_model.objects.create_superuser(
        username="test-staff", password="x"
    )
    client = Client(HTTP_HOST="localhost:8080")
    client.force_login(staff)
    with override_settings(GATEWAY_BASE_URL=base_url, ALLOWED_HOSTS=["localhost"]):
        response = client.post(
            reverse("backoffice-refund", args=[2147483647]),
            {"email": email, "password": password, "confirm": "on"},
        )
    assert response.status_code == 200
    assert "Не удалось подтвердить результат" in response.content.decode()
    assert AdminActionRecord.objects.filter(
        actor=staff, action="refund_payment", result_code="result_unknown"
    ).exists()
