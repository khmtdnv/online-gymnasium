"""Поиск и изменение ФИО через Gateway без локальной таблицы пользователей."""

from uuid import UUID

import httpx
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from backoffice_admin.forms import UpdateUserNameForm, UserSearchForm
from backoffice_admin.gateway_client import (
    GatewayBackofficeClient,
    GatewayProtocolError,
)
from backoffice_admin.models import AdminActionRecord


def _client() -> httpx.Client:
    """Создаёт клиент; вызывающая страница закрывает его через with."""
    return httpx.Client(
        base_url=settings.GATEWAY_BASE_URL, timeout=5.0, follow_redirects=False
    )


@require_GET
def search_students_view(request: HttpRequest) -> JsonResponse:
    """Возвращает подписи активных учеников только сотрудникам через admin_view."""
    form = UserSearchForm(request.GET)
    if not form.is_valid():
        response = JsonResponse({"error": "Введите от 2 до 200 символов."}, status=400)
    else:
        try:
            with _client() as client:
                users = GatewayBackofficeClient(
                    client, settings.GATEWAY_SERVICE_TOKEN
                ).search_users(form.cleaned_data["q"], students_only=True)
            response = JsonResponse(
                {
                    "results": [
                        {"id": str(user.id), "label": user.display_name}
                        for user in users
                    ]
                }
            )
        except (httpx.HTTPError, GatewayProtocolError):  # fmt: skip
            response = JsonResponse(
                {"error": "Не удалось найти учеников. Попробуйте позже."}, status=503
            )
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def list_users_view(request: HttpRequest) -> HttpResponse:
    """Показывает результаты поиска всех ролей со ссылками редактирования ФИО."""
    form = UserSearchForm(request.GET or None)
    users = []
    error = None
    if form.is_bound and form.is_valid():
        try:
            with _client() as client:
                users = GatewayBackofficeClient(
                    client, settings.GATEWAY_SERVICE_TOKEN
                ).search_users(form.cleaned_data["q"])
        except (httpx.HTTPError, GatewayProtocolError):  # fmt: skip
            error = "Не удалось загрузить пользователей из Gateway. Попробуйте позже."
    return render(
        request,
        "backoffice_admin/users.html",
        {
            **admin.site.each_context(request),
            "title": "Пользователи",
            "form": form,
            "users": users,
            "service_error": error,
        },
    )


@require_http_methods(["GET", "POST"])
def edit_user_name_view(request: HttpRequest, user_id: UUID) -> HttpResponse:
    """Редактирует только ФИО и журналирует результат без сохранения ФИО в аудите.

    Notes:
        Отказ связи после отправки не доказывает, что имя не изменилось.
        Ошибка локального аудита не отменяет уже выполненную команду Gateway.
    """
    form = UpdateUserNameForm(request.POST if request.method == "POST" else None)
    user = None
    error = None
    updating = False
    try:
        with _client() as client:
            gateway = GatewayBackofficeClient(client, settings.GATEWAY_SERVICE_TOKEN)
            user = gateway.get_user(user_id)
            if request.method == "GET":
                form = UpdateUserNameForm(
                    initial={
                        key: getattr(user, key)
                        for key in ("first_name", "last_name", "middle_name")
                    }
                )
            elif form.is_valid():
                updating = True
                gateway.update_user_name(user_id, **form.cleaned_data)
    except (httpx.HTTPError, GatewayProtocolError) as exc:
        missing = (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404
        )
        if missing:
            if updating:
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="update_user_name",
                    target_ids={"user_id": str(user_id)},
                    succeeded=False,
                    result_code="user_not_found",
                )
            return HttpResponse("Пользователь не найден.", status=404)
        error = "Не удалось получить результат Gateway. Обновите страницу и проверьте ФИО перед повтором."
        if updating:
            AdminActionRecord.objects.create(
                actor=request.user,
                action="update_user_name",
                target_ids={"user_id": str(user_id)},
                succeeded=False,
                result_code="gateway_result_unconfirmed",
            )
    else:
        if updating:
            AdminActionRecord.objects.create(
                actor=request.user,
                action="update_user_name",
                target_ids={"user_id": str(user_id)},
                succeeded=True,
                result_code="updated",
            )
            messages.success(request, "ФИО пользователя обновлено.")
            return redirect("backoffice-edit-user-name", user_id=user_id)
    return render(
        request,
        "backoffice_admin/edit_user_name.html",
        {
            **admin.site.each_context(request),
            "title": "Изменение ФИО",
            "form": form,
            "profile": user,
            "service_error": error,
            "can_submit": user is not None,
        },
    )
