"""Сотрудник управляет назначениями через Journal, без прямого доступа к его БД."""

from urllib.parse import urlencode

import httpx
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from backoffice_admin.forms import TeacherClassForm, UserSearchForm
from backoffice_admin.gateway_client import (
    GatewayBackofficeClient,
    GatewayProtocolError,
)
from backoffice_admin.journal_client import (
    JournalBackofficeClient,
    JournalProtocolError,
)
from backoffice_admin.models import AdminActionRecord


def _journal_http() -> httpx.Client:
    """Создаёт клиент Journal; вызывающий with закрывает соединения.

    Returns:
        HTTP-клиент с конечным timeout и запретом перенаправлений.
    """
    return httpx.Client(
        base_url=settings.JOURNAL_BASE_URL, timeout=5.0, follow_redirects=False
    )


@require_GET
def search_teachers_view(request: HttpRequest) -> JsonResponse:
    """Ищет активных преподавателей через Gateway; URL защищён admin_view.

    Args:
        request: GET с частью ФИО или email.

    Returns:
        Подписи/UUID без секретов, 400 неверный ввод или503 при сбое.
    """
    form = UserSearchForm(request.GET)
    if not form.is_valid():
        response = JsonResponse({"error": "Введите от 2 до 200 символов."}, status=400)
    else:
        try:
            with httpx.Client(
                base_url=settings.GATEWAY_BASE_URL, timeout=5.0, follow_redirects=False
            ) as client:
                users = GatewayBackofficeClient(
                    client, settings.GATEWAY_SERVICE_TOKEN
                ).search_users(form.cleaned_data["q"], role="teacher")
            response = JsonResponse(
                {"results": [{"id": str(x.id), "label": x.display_name} for x in users]}
            )
        except (httpx.HTTPError,GatewayProtocolError):  # fmt: skip
            response = JsonResponse(
                {"error": "Не удалось найти преподавателей. Попробуйте позже."},
                status=503,
            )
    response["Cache-Control"] = "no-store"
    return response


def _submit(
    request: HttpRequest, form: TeacherClassForm, journal: JournalBackofficeClient
) -> HttpResponse | None:
    """Отправляет команду и пишет подтверждённый либо неизвестный исход.

    Args:
        request: Запрос с действующей staff-сессией.
        form: Полностью проверенная форма.
        journal: Настроенный клиент Journal.

    Returns:
        Redirect при подтверждённом успехе, иначе None с ошибкой формы.

    Raises:
        DatabaseError: Локальный аудит не записан; выполненная команда не откатывается.
    """
    data = form.cleaned_data
    removing = data["action"] == "remove"
    targets = {"teacher_id": str(data["teacher_id"]), "class_id": data["class_id"]}
    try:
        if removing:
            journal.unassign_teacher_from_class(
                data["teacher_id"], data["class_id"], str(request.user.pk)
            )
            code = "removed"
        else:
            created = journal.assign_teacher_to_class(
                data["teacher_id"], data["class_id"], str(request.user.pk)
            )
            code = "created" if created else "already_exists"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        code = f"journal_http_{status}"
        message = {
            404: "Преподаватель или класс не найден. Обновите данные.",
            422: "Пользователь должен быть активным преподавателем.",
            503: "Проверка Gateway недоступна. Попробуйте позже.",
        }.get(status, "Journal отклонил запрос. Обратитесь к администратору.")
        if status >= 500 and status != 503:
            message = "Результат операции неизвестен. Проверьте список назначений перед повтором."
    except (httpx.RequestError,JournalProtocolError):  # fmt: skip
        code = "journal_result_unknown"
        message = "Результат операции неизвестен. Обновите список назначений; повтор той же команды безопасен."
    else:
        AdminActionRecord.objects.create(
            actor=request.user,
            action="unassign_teacher_from_class"
            if removing
            else "assign_teacher_to_class",
            succeeded=True,
            target_ids=targets,
            result_code=code,
        )
        if code == "already_exists":
            messages.info(request, "Преподаватель уже закреплён за этим классом.")
        else:
            messages.success(
                request,
                "Назначение снято."
                if removing
                else "Преподаватель закреплён за классом.",
            )
        query = urlencode(
            {
                "teacher_id": str(data["teacher_id"]),
                "teacher_label": request.POST.get("teacher_label", "")[:400],
            }
        )
        return redirect(reverse("backoffice-teacher-classes") + "?" + query)
    AdminActionRecord.objects.create(
        actor=request.user,
        action="unassign_teacher_from_class" if removing else "assign_teacher_to_class",
        succeeded=False,
        target_ids=targets,
        result_code=code,
    )
    form.add_error(None, message)
    return None


@require_http_methods(["GET", "POST"])
def teacher_classes_view(request: HttpRequest) -> HttpResponse:
    """Показывает назначения и обрабатывает команды с CSRF через admin_view.

    Args:
        request: GET выбора/списка либо POST назначения/снятия.

    Returns:
        Страница с формой и текущими классами либо redirect после успеха.
    """
    data = request.POST if request.method == "POST" else None
    raw_teacher = (
        request.POST.get("teacher_id")
        if data is not None
        else request.GET.get("teacher_id")
    )
    teacher_label = (
        request.POST.get("teacher_label", "")
        if data is not None
        else request.GET.get("teacher_label", "")
    )[:400]
    try:
        teacher_id = forms.UUIDField(required=False).clean(raw_teacher)
    except forms.ValidationError:
        teacher_id = None
    classes = []
    assigned = []
    service_error = None
    form = TeacherClassForm(
        data, classes=[], initial={"teacher_id": teacher_id, "action": "assign"}
    )
    configured = bool(
        getattr(settings, "JOURNAL_BASE_URL", None)
        and getattr(settings, "JOURNAL_SERVICE_TOKEN", None)
    )
    if not configured:
        service_error = (
            "Подключение к Journal не настроено. Обратитесь к администратору."
        )
    else:
        try:
            with _journal_http() as http:
                journal = JournalBackofficeClient(http, settings.JOURNAL_SERVICE_TOKEN)
                # Снятие не должно зависеть от Gateway или общего списка классов.
                if (
                    data is not None
                    and data.get("action") == "remove"
                    and form.is_valid()
                ):
                    result = _submit(request, form, journal)
                    if result is not None:
                        return result
                classes = journal.list_classes()
                if not (data is not None and data.get("action") == "remove"):
                    form = TeacherClassForm(
                        data,
                        classes=classes,
                        initial={"teacher_id": teacher_id, "action": "assign"},
                    )
                    if data is not None and form.is_valid():
                        result = _submit(request, form, journal)
                        if result is not None:
                            return result
                if teacher_id:
                    assigned = journal.list_classes_for_teacher(teacher_id)
        except (httpx.HTTPError,JournalProtocolError):  # fmt: skip
            service_error = "Не удалось загрузить данные Journal. Обновите страницу для проверки текущих назначений."
    # Ошибки команды снятия остаются в form, но её технический список из одной
    # пары нельзя показывать как варианты для новой команды назначения.
    assignment_form = (
        TeacherClassForm(
            classes=classes, initial={"teacher_id": teacher_id, "action": "assign"}
        )
        if data is not None and data.get("action") == "remove"
        else form
    )
    return render(
        request,
        "backoffice_admin/teacher_classes.html",
        {
            **admin.site.each_context(request),
            "title": "Преподаватели и классы",
            "form": form,
            "assignment_form": assignment_form,
            "teacher_id": teacher_id,
            "teacher_label": teacher_label,
            "assigned_classes": assigned,
            "service_error": service_error,
            "can_assign": configured
            and bool(classes)
            and service_error is None
            and teacher_id is not None,
        },
    )
