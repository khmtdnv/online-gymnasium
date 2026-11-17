from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_access_verification_uses_gateway_and_rejects_invalid_json(monkeypatch):
    from pydantic import ValidationError

    from backoffice_admin import sso_views

    user_id, session_id = uuid4(), uuid4()
    real_client = httpx.Client
    valid = True

    def handle(request):
        assert request.headers["authorization"] == "Bearer access"
        assert request.headers["x-backoffice-service-token"] == "test-service-token"
        return httpx.Response(
            200,
            json={"user_id": str(user_id), "session_id": str(session_id)}
            if valid
            else {},
        )

    monkeypatch.setattr(
        sso_views.httpx,
        "Client",
        lambda **kw: real_client(**kw, transport=httpx.MockTransport(handle)),
    )
    assert sso_views.verify_access_token("access") == (user_id, session_id)
    valid = False
    with pytest.raises(ValidationError):
        sso_views.verify_access_token("access")


def test_sso_requires_explicit_link_and_preserves_django_permissions(
    client, django_user_model
):
    from backoffice_admin.models import GatewayIdentity

    user = django_user_model.objects.create_user(username="staff", is_staff=True)
    gateway_id, session_id = uuid4(), uuid4()
    path = reverse("backoffice-sso")
    headers = {"HTTP_AUTHORIZATION": "Bearer test-access"}
    with patch(
        "backoffice_admin.sso_views.verify_access_token",
        return_value=(gateway_id, session_id),
    ):
        assert client.post(path, **headers).status_code == 403
        GatewayIdentity.objects.create(user=user, gateway_user_id=gateway_id)
        assert client.post(path, **headers).status_code == 204
    session = client.session
    assert session["gateway_user_id"] == str(gateway_id)
    assert session["gateway_session_id"] == str(session_id)
    assert session["_auth_user_id"] == str(user.pk)
    assert not user.is_superuser


def test_sso_rejects_missing_token_and_unprotected_post(django_user_model):
    path = reverse("backoffice-sso")
    client = Client(enforce_csrf_checks=True)
    assert client.post(path, HTTP_AUTHORIZATION="Bearer test").status_code == 403
    assert Client().post(path).status_code == 401


def test_sso_admin_access_stops_when_gateway_session_revoked(client, django_user_model):
    from backoffice_admin.models import GatewayIdentity

    user = django_user_model.objects.create_user(username="staff", is_staff=True)
    gateway_id, session_id = uuid4(), uuid4()
    GatewayIdentity.objects.create(user=user, gateway_user_id=gateway_id)
    with patch(
        "backoffice_admin.sso_views.verify_access_token",
        return_value=(gateway_id, session_id),
    ):
        assert (
            client.post(
                reverse("backoffice-sso"), HTTP_AUTHORIZATION="Bearer test"
            ).status_code
            == 204
        )
    with patch(
        "backoffice_admin.sso_middleware.check_gateway_session", return_value=True
    ):
        assert client.get("/admin/").status_code == 200
    with patch(
        "backoffice_admin.sso_middleware.check_gateway_session", return_value=False
    ):
        assert client.get("/admin/").status_code == 401
    assert "_auth_user_id" not in client.session


def test_sso_fails_closed_if_gateway_unavailable(client, django_user_model):
    import httpx

    from backoffice_admin.models import GatewayIdentity

    user = django_user_model.objects.create_user(username="staff", is_staff=True)
    gateway_id, session_id = uuid4(), uuid4()
    GatewayIdentity.objects.create(user=user, gateway_user_id=gateway_id)
    with patch(
        "backoffice_admin.sso_views.verify_access_token",
        return_value=(gateway_id, session_id),
    ):
        assert (
            client.post(
                reverse("backoffice-sso"), HTTP_AUTHORIZATION="Bearer test"
            ).status_code
            == 204
        )
    with patch(
        "backoffice_admin.sso_middleware.check_gateway_session",
        side_effect=httpx.ConnectError("unavailable"),
    ):
        assert client.get("/admin/").status_code == 503


def test_admin_logout_revokes_shared_gateway_session(client, django_user_model):
    from backoffice_admin.models import GatewayIdentity

    user = django_user_model.objects.create_user(username="staff", is_staff=True)
    gateway_id, session_id = uuid4(), uuid4()
    GatewayIdentity.objects.create(user=user, gateway_user_id=gateway_id)
    with patch(
        "backoffice_admin.sso_views.verify_access_token",
        return_value=(gateway_id, session_id),
    ):
        assert (
            client.post(
                reverse("backoffice-sso"), HTTP_AUTHORIZATION="Bearer test"
            ).status_code
            == 204
        )
    with (
        patch(
            "backoffice_admin.sso_middleware.check_gateway_session", return_value=True
        ),
        patch("backoffice_admin.sso_views.revoke_gateway_session") as revoke,
    ):
        response = client.post("/admin/logout/")
    assert response.status_code == 302
    revoke.assert_called_once_with(gateway_id, session_id)
    assert "_auth_user_id" not in client.session
