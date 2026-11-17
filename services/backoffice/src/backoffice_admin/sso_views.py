"""Переход в Backoffice после подтверждения учётной записи Gateway."""

from uuid import UUID

import httpx
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from pydantic import BaseModel, ConfigDict, ValidationError

from backoffice_admin.models import GatewayIdentity


class VerifiedIdentity(BaseModel):
    """Идентификаторы, подтверждённые внутренней ручкой Gateway."""

    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    session_id: UUID


def verify_access_token(token: str) -> tuple[UUID, UUID]:
    """Проверяет токен через Gateway; недействительный ответ отклоняется."""
    with httpx.Client(base_url=settings.GATEWAY_BASE_URL, timeout=5.0) as client:
        response = client.get(
            "/internal/backoffice/identity",
            headers={
                "X-Backoffice-Service-Token": settings.GATEWAY_SERVICE_TOKEN,
                "Authorization": f"Bearer {token}",
            },
        )
        response.raise_for_status()
        identity = VerifiedIdentity.model_validate_json(response.content)
        return identity.user_id, identity.session_id


def revoke_gateway_session(user_id: UUID, session_id: UUID) -> None:
    """Отзывает серверную сессию без передачи браузерного refresh-токена."""
    with httpx.Client(base_url=settings.GATEWAY_BASE_URL, timeout=5.0) as client:
        response = client.post(
            "/internal/backoffice/session/revoke",
            headers={"X-Backoffice-Service-Token": settings.GATEWAY_SERVICE_TOKEN},
            json={"user_id": str(user_id), "session_id": str(session_id)},
        )
        response.raise_for_status()
        if response.status_code != 204:
            raise httpx.ProtocolError("Unexpected revoke response")


@never_cache
@ensure_csrf_cookie
@require_GET
def sso_csrf(request: HttpRequest) -> HttpResponse:
    """Выдаёт CSRF-cookie перед POST обмена токена."""
    return HttpResponse(status=204)


@never_cache
@require_POST
def sso_login(request: HttpRequest) -> HttpResponse:
    """Создаёт Django-сессию только для явно связанного сотрудника."""
    scheme, separator, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or len(token) > 4096:
        return HttpResponse(status=401)
    try:
        gateway_user_id, gateway_session_id = verify_access_token(token)
    except httpx.HTTPStatusError as exc:
        return HttpResponse(
            status=401 if exc.response.status_code in (401, 403) else 503
        )
    except httpx.RequestError, ValidationError:
        return HttpResponse(status=503)
    identity = (
        GatewayIdentity.objects.select_related("user")
        .filter(gateway_user_id=gateway_user_id)
        .first()
    )
    if identity is None or not identity.user.is_active or not identity.user.is_staff:
        return HttpResponse(status=403)
    login(request, identity.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["gateway_user_id"] = str(gateway_user_id)
    request.session["gateway_session_id"] = str(gateway_session_id)
    return HttpResponse(status=204)


@never_cache
@require_POST
def admin_logout(request: HttpRequest) -> HttpResponse:
    """При SSO отзывает общую сессию; прежний вход Django сохраняет свой выход."""
    user_id = request.session.get("gateway_user_id")
    session_id = request.session.get("gateway_session_id")
    if not user_id and not session_id:
        return admin.site.logout(request)
    try:
        revoke_gateway_session(UUID(user_id), UUID(session_id))
    except httpx.HTTPError, ValueError, TypeError, AttributeError:
        logout(request)
        return HttpResponse(
            "Выход выполнен локально, отзыв общей сессии не подтверждён.", status=503
        )
    logout(request)
    return redirect("/login")
