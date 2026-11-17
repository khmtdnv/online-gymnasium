"""Сотрудник без прав суперпользователя не видит историю платежей."""

from datetime import date
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_billing_requires_superuser_and_shows_named_history(client, django_user_model):
    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    admin = django_user_model.objects.create_superuser(username="admin", password="x")
    path = reverse("backoffice-billing")
    client.force_login(staff)
    with patch("backoffice_admin.billing_views.read_payments") as read:
        assert client.get(path).status_code == 403
        read.assert_not_called()
    client.force_login(admin)
    with patch("backoffice_admin.billing_views.read_payments") as read:
        read.return_value = {
            "payments": [
                {
                    "id": 7,
                    "student_name": "Петров Иван",
                    "study_month": "2026-10-01",
                    "amount_rubles": "3000.00",
                    "status": "succeeded",
                    "refund_status": None,
                }
            ]
        }
        response = client.get(path)
        assert response.status_code == 200
        assert "Петров Иван" in response.content.decode()
        assert "3000.00" in response.content.decode()


def test_payment_reader_formats_amount_and_translates_status(monkeypatch):
    """Показывает имена и понятные статусы без округлений float."""
    from backoffice_admin import billing_views

    real_client = httpx.Client

    def handler(request):
        assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
        assert request.url.params["offset"] == "50"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 7,
                    "student_name": "Петров Иван",
                    "study_month": "2026-10-01",
                    "amount_kopecks": 123456,
                    "status": "succeeded",
                    "refund_status": None,
                }
            ],
        )

    monkeypatch.setattr(
        billing_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    report = billing_views.read_payments(50)
    payment = report["payments"][0]
    assert payment.amount_rubles == "1234.56"
    assert payment.status_label == "Оплачен"
    assert report["previous_offset"] == 0


def test_pending_refund_can_be_retried_after_page_reload():
    """Потерянный ответ не скрывает действие, необходимое для повтора."""
    from backoffice_admin.billing_views import PaymentInfo

    payment = PaymentInfo(
        id=7,
        student_name="Петров Иван",
        study_month=date(2026, 10, 1),
        amount_kopecks=300000,
        status="succeeded",
        refund_status="unknown",
    )
    assert payment.refund_action_label == "Повторить запрос возврата"


def test_refund_requires_verified_gateway_admin_and_reuses_request_key(
    client, django_user_model, monkeypatch
):
    """Повтор после сбоя использует прежний ключ и сохраняет обе личности."""
    from backoffice_admin import billing_views
    from backoffice_admin.models import AdminActionRecord, AdminEventOutbox

    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    admin = django_user_model.objects.create_superuser(username="admin", password="x")
    path = reverse("backoffice-refund", args=[7])
    client.force_login(staff)
    assert client.post(path, {}).status_code == 403
    client.force_login(admin)
    sent_keys = []
    cookies = []
    real_client = httpx.Client
    gateway_admin = UUID("75ef34f4-2588-41b1-b41e-cbd058c6025c")

    def handler(request):
        if request.url.path.endswith("/login"):
            assert request.headers["origin"] == "http://testserver"
            return httpx.Response(
                200,
                json={"access_token": "private-access"},
                headers={
                    "Set-Cookie": "refresh_token=private-refresh; Path=/api/v1/auth; Secure; HttpOnly"
                },
            )
        if request.url.path.endswith("/me"):
            assert request.headers["authorization"] == "Bearer private-access"
            return httpx.Response(
                200,
                json={
                    "id": str(gateway_admin),
                    "email": "admin@example.test",
                    "role": "admin",
                },
            )
        if request.url.path.endswith("/logout"):
            cookies.append(request.headers.get("cookie", ""))
            return httpx.Response(204)
        assert request.url.path == "/api/v1/billing/payments/7/refund"
        assert request.extensions["timeout"]["read"] == 70.0
        import json

        sent_keys.append(json.loads(request.content)["request_key"])
        return httpx.Response(
            202, json={"id": 7, "status": "pending", "refund_status": "pending"}
        )

    monkeypatch.setattr(
        billing_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    body = {"email": "admin@example.test", "password": "not-logged", "confirm": "on"}
    assert client.post(path, body).status_code == 302
    assert client.post(path, body).status_code == 302
    assert len(sent_keys) == 2 and sent_keys[0] == sent_keys[1]
    assert cookies == ["refresh_token=private-refresh"] * 2
    records = AdminActionRecord.objects.filter(action="refund_payment")
    assert records.count() == 4
    assert all(row.actor_id == admin.id for row in records)
    assert all(
        row.target_ids == {"payment_id": 7, "user_id": str(gateway_admin)}
        for row in records
    )
    assert all(
        "not-logged" not in str(item.envelope)
        for item in AdminEventOutbox.objects.all()
    )


def test_refund_rejects_non_admin_and_revokes_temporary_session(
    client, django_user_model, monkeypatch
):
    """Django-суперпользователь не может вернуть платёж с ролью ученика."""
    from backoffice_admin import billing_views
    from backoffice_admin.models import AdminActionRecord

    user = django_user_model.objects.create_superuser(username="admin", password="x")
    client.force_login(user)
    calls = []
    real_client = httpx.Client

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(
                200,
                json={"access_token": "token"},
                headers={
                    "Set-Cookie": "refresh_token=refresh; Path=/api/v1/auth; Secure"
                },
            )
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={"id": "75ef34f4-2588-41b1-b41e-cbd058c6025c", "role": "student"},
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(204)
        pytest.fail("Запрос возврата для ученика не должен отправляться")

    monkeypatch.setattr(
        billing_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    response = client.post(
        reverse("backoffice-refund", args=[7]),
        {"email": "student@example.test", "password": "secret-input", "confirm": "on"},
    )
    assert response.status_code == 200
    assert "secret-input" not in response.content.decode()
    assert calls == ["/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout"]
    assert not AdminActionRecord.objects.filter(action="refund_payment").exists()


def test_reconcile_uses_gateway_admin_and_records_staff_actor(
    client, django_user_model, monkeypatch
):
    """Ручная сверка отправляет ID провайдера без ручной смены статуса."""
    from backoffice_admin import billing_views
    from backoffice_admin.models import AdminActionRecord

    user = django_user_model.objects.create_superuser(username="admin", password="x")
    client.force_login(user)
    real_client = httpx.Client
    provider_id = "5ce8f500-51c6-49ef-b761-7588f425b131"
    sent = []

    def handler(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(
                200,
                json={"access_token": "token"},
                headers={"Set-Cookie": "refresh_token=refresh; Path=/api/v1/auth"},
            )
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={"id": "75ef34f4-2588-41b1-b41e-cbd058c6025c", "role": "admin"},
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(204)
        assert request.url.path == "/api/v1/billing/payments/7/reconcile"
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"id": 7, "status": "pending", "refund_status": None}
        )

    monkeypatch.setattr(
        billing_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    response = client.post(
        reverse("backoffice-reconcile", args=[7]),
        {
            "email": "admin@example.test",
            "password": "secret",
            "confirm": "on",
            "provider_id": provider_id,
        },
    )
    assert response.status_code == 302
    assert sent == [{"provider_id": provider_id}]
    assert AdminActionRecord.objects.filter(
        actor=user, action="reconcile_payment", result_code="request_accepted"
    ).exists()


def test_refund_timeout_keeps_retry_key_and_hides_password(
    client, django_user_model, monkeypatch
):
    """Неизвестный результат не превращается в новый запрос с другим ключом."""
    import json

    from backoffice_admin import billing_views
    from backoffice_admin.models import AdminActionRecord

    user = django_user_model.objects.create_superuser(username="admin", password="x")
    client.force_login(user)
    real_client = httpx.Client
    keys = []

    def handler(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(
                200,
                json={"access_token": "token"},
                headers={"Set-Cookie": "refresh_token=refresh; Path=/api/v1/auth"},
            )
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={"id": "75ef34f4-2588-41b1-b41e-cbd058c6025c", "role": "admin"},
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(204)
        keys.append(json.loads(request.content)["request_key"])
        raise httpx.ReadTimeout("private details", request=request)

    monkeypatch.setattr(
        billing_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    path = reverse("backoffice-refund", args=[7])
    body = {"email": "admin@example.test", "password": "secret-input", "confirm": "on"}
    for _ in range(2):
        response = client.post(path, body)
        assert response.status_code == 200
        assert "secret-input" not in response.content.decode()
        assert "private details" not in response.content.decode()
    assert len(keys) == 2 and keys[0] == keys[1]
    assert (
        AdminActionRecord.objects.filter(
            action="refund_payment", result_code="result_unknown"
        ).count()
        == 2
    )


def test_refund_rejects_post_without_csrf(django_user_model):
    """Финансовое действие нельзя отправить без CSRF-токена."""
    from django.test import Client

    user = django_user_model.objects.create_superuser(username="admin", password="x")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post(
        reverse("backoffice-refund", args=[7]),
        {"email": "admin@example.test", "password": "secret", "confirm": "on"},
    )
    assert response.status_code == 403
