"""Перевод и завершение пребывания ученика через API Journal."""

from uuid import UUID

import httpx
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from backoffice_admin.forms import ChangeStudentClassForm
from backoffice_admin.gateway_client import (
    GatewayBackofficeClient,
    GatewayProtocolError,
)
from backoffice_admin.journal_client import (
    JournalBackofficeClient,
    JournalProtocolError,
)
from backoffice_admin.models import AdminActionRecord


@require_http_methods(["GET", "POST"])
def change_student_class_view(request: HttpRequest, student_id: UUID) -> HttpResponse:
    """Показывает исходный период и не подменяет его ID при отправке формы.

    Args:
        request: Staff-запрос страницы либо POST подтверждённого действия.
        student_id: UUID выбранного в поиске ученика.

    Returns:
        Страница с формой/ошибкой либо redirect после подтверждённого успеха.
    """
    profile = None
    if request.method == "GET":
        try:
            with httpx.Client(
                base_url=settings.GATEWAY_BASE_URL, timeout=5.0, follow_redirects=False
            ) as http:
                profile = GatewayBackofficeClient(
                    http, settings.GATEWAY_SERVICE_TOKEN
                ).get_user(student_id)
        except (httpx.HTTPError, GatewayProtocolError):  # fmt: skip
            # ФИО нужно для отображения, но закрыть период отключённого пользователя можно.
            profile = None

    data = request.POST if request.method == "POST" else None
    current = None
    classes = []
    service_error = None
    classes_error = None
    refresh_required = False
    form = ChangeStudentClassForm(data, classes=[])
    if not settings.JOURNAL_BASE_URL or not settings.JOURNAL_SERVICE_TOKEN:
        service_error = (
            "Подключение к Journal не настроено. Обратитесь к администратору."
        )
    else:
        try:
            with httpx.Client(
                base_url=settings.JOURNAL_BASE_URL, timeout=5.0, follow_redirects=False
            ) as http:
                journal = JournalBackofficeClient(http, settings.JOURNAL_SERVICE_TOKEN)
                current = journal.get_current_period_for_student(student_id)
                try:
                    classes = journal.list_classes()
                except (httpx.HTTPError, JournalProtocolError):  # fmt: skip
                    classes_error = (
                        "Список классов недоступен. Перевод временно невозможен."
                    )
                initial = {"operation": "transfer"}
                if current is not None:
                    initial["expected_period_id"] = current.id
                # POST хранит expected сотрудника: свежий current не заменяет его.
                form = ChangeStudentClassForm(
                    data, classes=classes, initial=initial if data is None else None
                )
                if data is not None and form.is_valid():
                    response, refresh_required = _submit_period_change(
                        request, student_id, form, journal
                    )
                    if response is not None:
                        return response
        except (httpx.HTTPError, JournalProtocolError):  # fmt: skip
            service_error = (
                "Не удалось прочитать текущий класс из Journal. Попробуйте позже."
            )

    current_class_label = None
    if current is not None:
        current_class_label = f"Класс ID {current.class_id}"
        for item in classes:
            if item.id == current.class_id:
                current_class_label = (
                    f"{item.name} · {item.study_year}/{item.study_year + 1}"
                )
                break
    return render(
        request,
        "backoffice_admin/change_student_class.html",
        {
            **admin.site.each_context(request),
            "title": "Класс ученика",
            "profile": profile,
            "current": current,
            "current_class_label": current_class_label,
            "form": form,
            "service_error": service_error,
            "classes_error": classes_error,
            "can_submit": current is not None
            and service_error is None
            and not refresh_required,
        },
    )


def _submit_period_change(
    request: HttpRequest,
    student_id: UUID,
    form: ChangeStudentClassForm,
    journal: JournalBackofficeClient,
) -> tuple[HttpResponse | None, bool]:
    """Отправляет ровно одну команду и журналирует подтверждённый/неизвестный итог.

    Args:
        request: Запрос сотрудника; actor берётся только из request.user.pk.
        student_id: UUID из адреса страницы выбранного ученика.
        form: Проверенные данные, включая исходный expected_period_id.
        journal: Служебный клиент без автоматического повтора команды.

    Returns:
        Ответ при успехе и признак необходимости заново открыть форму при ошибке.

    Raises:
        django.db.DatabaseError: Локальный аудит не сохранён; это не отменяет
            уже подтверждённое действие в Journal.
    """
    operation = form.cleaned_data["operation"]
    expected = form.cleaned_data["expected_period_id"]
    targets = {"student_id": str(student_id), "expected_period_id": expected}
    action = (
        "transfer_student_to_class"
        if operation == "transfer"
        else "end_student_class_period"
    )
    if operation == "transfer":
        targets["target_class_id"] = form.cleaned_data["target_class_id"]
    try:
        if operation == "transfer":
            period = journal.transfer_student_to_class(
                student_id,
                form.cleaned_data["target_class_id"],
                expected,
                str(request.user.pk),
            )
            targets["period_id"] = period.id
            code = "unchanged" if period.id == expected else "transferred"
        else:
            journal.end_student_class_period(student_id, expected, str(request.user.pk))
            code = "ended"
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        code = f"journal_http_{status}"
        message = {
            404: "Ученик или класс не найден. Обновите форму.",
            409: "Текущий период уже изменился. Обновите форму и проверьте класс ученика.",
            422: "Journal отклонил данные. Проверьте, что пользователь — активный ученик.",
        }.get(
            status,
            "Не удалось подтвердить результат. Обновите страницу и проверьте текущий класс.",
        )
    except httpx.RequestError:
        code = "journal_result_unknown"
        message = "Результат операции неизвестен: ответ Journal не получен. Обновите страницу и проверьте текущий класс перед новым действием."
    except JournalProtocolError:
        code = "journal_protocol_error"
        message = "Journal вернул некорректный ответ. Обновите страницу и проверьте текущий класс."
    else:
        AdminActionRecord.objects.create(
            actor=request.user,
            action=action,
            succeeded=True,
            target_ids=targets,
            result_code=code,
        )
        messages.success(
            request,
            "Ученик переведён в выбранный класс."
            if code == "transferred"
            else "Ученик уже состоит в этом классе."
            if code == "unchanged"
            else "Пребывание в классе завершено; история сохранена.",
        )
        return redirect("backoffice-change-student-class", student_id=student_id), False
    AdminActionRecord.objects.create(
        actor=request.user,
        action=action,
        succeeded=False,
        target_ids=targets,
        result_code=code,
    )
    form.add_error(None, message)
    return None, True
