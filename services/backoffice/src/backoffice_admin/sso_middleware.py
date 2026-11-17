"""Проверяет связанную серверную сессию перед доступом к админке."""

from uuid import UUID

import httpx
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponse

from backoffice_admin.models import GatewayIdentity


def check_gateway_session(user_id: UUID, session_id: UUID) -> bool:
    """Запрашивает актуальность сессии и роли доверенным вызовом Gateway."""
    with httpx.Client(base_url=settings.GATEWAY_BASE_URL, timeout=5.0) as client:
        response = client.post(
            "/internal/backoffice/session",
            headers={"X-Backoffice-Service-Token": settings.GATEWAY_SERVICE_TOKEN},
            json={"user_id": str(user_id), "session_id": str(session_id)},
        )
        if response.status_code == 401:
            return False
        response.raise_for_status()
        if response.status_code != 204:
            raise httpx.ProtocolError("Unexpected session check response")
        return True


class GatewaySessionMiddleware:
    """Не пропускает SSO-сессию после отзыва или изменения связи аккаунтов."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        gateway_user_id = request.session.get("gateway_user_id")
        gateway_session_id = request.session.get("gateway_session_id")
        if (
            request.path_info.startswith("/admin/")
            and request.path_info not in {"/admin/sso/", "/admin/sso/csrf/"}
            and (gateway_user_id or gateway_session_id)
        ):
            try:
                user_id, session_id = UUID(gateway_user_id), UUID(gateway_session_id)
                if (
                    not request.user.is_authenticated
                    or not GatewayIdentity.objects.filter(
                        user_id=request.user.pk, gateway_user_id=user_id
                    ).exists()
                ):
                    logout(request)
                    return HttpResponse(status=401)
                if not check_gateway_session(user_id, session_id):
                    logout(request)
                    return HttpResponse(status=401)
            except ValueError, TypeError, AttributeError:
                logout(request)
                return HttpResponse(status=401)
            except httpx.HTTPError:
                return HttpResponse(status=503)
        return self.get_response(request)
