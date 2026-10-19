"""Страницы административных команд над пользователями Gateway."""

import httpx
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from backoffice_admin.forms import CreateUserForm, LinkParentStudentForm
from backoffice_admin.gateway_client import (
    GatewayBackofficeClient,
    GatewayProtocolError,
    GatewayUserAlreadyExistsError,
)
from backoffice_admin.models import AdminActionRecord


@require_http_methods(["GET", "POST"])
def create_user_view(request: HttpRequest) -> HttpResponse:
    """Проверяет форму, создаёт пользователя через Gateway и записывает результат.

    Args:
        request: GET-запрос страницы или POST-запрос с данными формы сотрудника.

    Returns:
        HTML-страница с пустой формой или ошибками проверки либо перенаправление
        на страницу формы после успешного создания пользователя.

    Raises:
        django.db.DatabaseError: Не удалось сохранить запись журнала действий.

    Notes:
        Занятый email отображается как ошибка поля. Ошибки запроса, HTTP-статуса
        и контракта ответа отображаются как ошибки всей формы. Результаты
        обращений записываются в журнал; сбой связи не доказывает, что Gateway
        не создал пользователя.
        Пароль и служебный токен в журнал не сохраняются. Ошибка локального
        журналирования не отменяет создание пользователя в Gateway.
    """
    if request.method == "POST":
        form = CreateUserForm(request.POST)

        if form.is_valid():
            try:
                with httpx.Client(
                    base_url=settings.GATEWAY_BASE_URL,
                    timeout=5.0,
                ) as http_client:
                    gateway = GatewayBackofficeClient(
                        http_client=http_client,
                        service_token=settings.GATEWAY_SERVICE_TOKEN,
                    )
                    created_user = gateway.create_user(
                        email=form.cleaned_data["email"],
                        password=form.cleaned_data["password"],
                        role=form.cleaned_data["role"],
                        **{
                            key: form.cleaned_data[key]
                            for key in ("first_name", "last_name", "middle_name")
                            if form.cleaned_data[key]
                        },
                    )

            except httpx.RequestError:
                form.add_error(
                    None,
                    "Не удалось получить результат от Gateway. "
                    "Перед повторной отправкой проверьте, создан ли пользователь.",
                )
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="create_user",
                    succeeded=False,
                    target_ids={},
                    result_code="gateway_result_unknown",
                )

            except httpx.HTTPStatusError as exc:
                form.add_error(
                    None,
                    "Gateway вернул ошибку. Обратитесь к администратору.",
                )
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="create_user",
                    succeeded=False,
                    target_ids={},
                    result_code=f"gateway_http_{exc.response.status_code}",
                )

            except GatewayUserAlreadyExistsError:
                form.add_error("email", "Пользователь с таким email уже существует.")
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="create_user",
                    succeeded=False,
                    target_ids={},
                    result_code="email_already_exists",
                )

            except GatewayProtocolError:
                form.add_error(
                    None,
                    "Gateway вернул некорректный ответ. "
                    "Перед повторной отправкой проверьте, создан ли пользователь.",
                )
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="create_user",
                    succeeded=False,
                    target_ids={},
                    result_code="gateway_protocol_error",
                )

            else:
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="create_user",
                    succeeded=True,
                    target_ids={"user_id": str(created_user.id)},
                    result_code="created",
                )
                messages.success(request, f"Пользователь {created_user.email} создан.")

                return redirect("backoffice-create-user")

    else:
        form = CreateUserForm()

    context = {
        **admin.site.each_context(request),
        "title": "Создание пользователя",
        "form": form,
    }

    return render(request, "backoffice_admin/create_user.html", context)


@require_http_methods(["GET", "POST"])
def link_parent_student_view(request: HttpRequest) -> HttpResponse:
    """Отправляет привязку родителя к ученику в Gateway и записывает результат.

    Args:
        request: GET-запрос страницы или POST-запрос с двумя UUID.

    Returns:
        Страница формы с ошибками либо перенаправление после успешной привязки.
        Уже существующая связь также считается успешным результатом.

    Raises:
        django.db.DatabaseError: Не удалось сохранить журнал действий.

    Notes:
        Сбой связи не доказывает отсутствие привязки в Gateway.
        Ошибка локального журнала не отменяет выполненную привязку.
    """
    if request.method == "POST":
        form = LinkParentStudentForm(request.POST)
        if form.is_valid():
            try:
                with httpx.Client(
                    base_url=settings.GATEWAY_BASE_URL,
                    timeout=5.0,
                ) as http_client:
                    gateway = GatewayBackofficeClient(
                        http_client=http_client,
                        service_token=settings.GATEWAY_SERVICE_TOKEN,
                    )
                    created = gateway.link_parent_student(
                        parent_id=form.cleaned_data["parent_id"],
                        student_id=form.cleaned_data["student_id"],
                    )

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    form.add_error(None, "Родитель или ученик не найден.")
                elif exc.response.status_code == 422:
                    form.add_error(
                        None,
                        "У пользователей должны быть роли родителя и ученика соответственно.",
                    )
                else:
                    form.add_error(
                        None,
                        "Gateway вернул ошибку. Обратитесь к администратору.",
                    )

                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="link_parent_student",
                    succeeded=False,
                    target_ids={
                        "parent_id": str(form.cleaned_data["parent_id"]),
                        "student_id": str(form.cleaned_data["student_id"]),
                    },
                    result_code=f"gateway_http_{exc.response.status_code}",
                )

            except httpx.RequestError:
                form.add_error(
                    None,
                    "Не удалось получить результат от Gateway. "
                    "Проверьте наличие связи перед повторной отправкой.",
                )
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="link_parent_student",
                    succeeded=False,
                    target_ids={
                        "parent_id": str(form.cleaned_data["parent_id"]),
                        "student_id": str(form.cleaned_data["student_id"]),
                    },
                    result_code="gateway_result_unknown",
                )

            except GatewayProtocolError:
                form.add_error(
                    None,
                    "Gateway вернул некорректный ответ. "
                    "Проверьте наличие связи перед повторной отправкой.",
                )
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="link_parent_student",
                    succeeded=False,
                    target_ids={
                        "parent_id": str(form.cleaned_data["parent_id"]),
                        "student_id": str(form.cleaned_data["student_id"]),
                    },
                    result_code="gateway_protocol_error",
                )

            else:
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action="link_parent_student",
                    succeeded=True,
                    target_ids={
                        "parent_id": str(form.cleaned_data["parent_id"]),
                        "student_id": str(form.cleaned_data["student_id"]),
                    },
                    result_code="created" if created else "already_exists",
                )

                if created:
                    messages.success(request, "Связь родителя и ученика создана.")
                else:
                    messages.info(request, "Связь родителя и ученика уже существует.")

                return redirect("backoffice-link-parent-student")

    else:
        form = LinkParentStudentForm()

    context = {
        **admin.site.each_context(request),
        "title": "Создание связи между родителем и учеником",
        "form": form,
    }

    return render(request, "backoffice_admin/link_parent_student.html", context)
