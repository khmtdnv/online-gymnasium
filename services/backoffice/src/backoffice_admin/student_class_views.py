"""Страница назначения ученика в класс через API Journal."""

import httpx
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from backoffice_admin.forms import AddStudentToClassForm
from backoffice_admin.journal_client import (
    JournalBackofficeClient,
    JournalProtocolError,
)
from backoffice_admin.models import AdminActionRecord


@require_http_methods(["GET", "POST"])
def add_student_to_class_view(request: HttpRequest) -> HttpResponse:
    """Загружает классы и обрабатывает форму без локальной копии данных Journal.

    Args:
        request: GET страницы либо POST с UUID ученика и выбранным классом.

    Returns:
        Форма с результатом проверки либо redirect после успешной команды.

    Notes:
        URL обёрнут admin.site.admin_view. Список заново загружается и на POST;
        неизвестный вариант не принимается. Journal окончательно проверяет
        существование класса и ученика. При сбое загрузки команда не отправляется.
    """
    data = request.POST if request.method == "POST" else None
    form = AddStudentToClassForm(data, classes=[])
    service_error = None
    classes = []
    if not settings.JOURNAL_BASE_URL or not settings.JOURNAL_SERVICE_TOKEN:
        service_error = (
            "Подключение к Journal не настроено. Обратитесь к администратору."
        )
    else:
        try:
            with httpx.Client(
                base_url=settings.JOURNAL_BASE_URL,
                timeout=5.0,
                follow_redirects=False,
            ) as http_client:
                journal = JournalBackofficeClient(
                    http_client, settings.JOURNAL_SERVICE_TOKEN
                )
                classes = journal.list_classes()
                form = AddStudentToClassForm(data, classes=classes)
                if request.method == "POST" and form.is_valid():
                    result = _submit_student_form(request, form, journal)
                    if result is not None:
                        return result
        except (httpx.HTTPError, JournalProtocolError):  # fmt: skip
            classes = []
            service_error = "Не удалось загрузить классы из Journal. Попробуйте позже."
        else:
            if not classes:
                service_error = "В Journal пока нет классов. Сначала создайте класс."

    if service_error and data is not None:
        # Только отображение прежнего ввода: без полного списка проверять его нельзя.
        form = AddStudentToClassForm(initial=data, classes=[])
        selected_id = data.get("class_id", "")
        if selected_id:
            form.fields["class_id"].choices = [
                (selected_id, f"Класс ID {selected_id} (список недоступен)")
            ]
        form.fields["class_id"].disabled = True

    return render(
        request,
        "backoffice_admin/add_student_to_class.html",
        {
            **admin.site.each_context(request),
            "title": "Добавление ученика в класс",
            "form": form,
            "service_error": service_error,
            "can_submit": bool(classes) and service_error is None,
        },
    )


def _submit_student_form(
    request: HttpRequest, form: AddStudentToClassForm, journal: JournalBackofficeClient
) -> HttpResponse | None:
    """Отправляет одну команду и записывает её подтверждённый либо неизвестный итог.

    Args:
        request: Запрос аутентифицированного сотрудника Django.
        form: Валидная форма с нормализованными UUID и целочисленным ID класса.
        journal: Клиент с отдельным служебным секретом Journal.

    Returns:
        Redirect при успехе; None, если ошибка добавлена в форму.

    Raises:
        django.db.DatabaseError: Не удалось сохранить локальный журнал действий.

    Notes:
        Сбой связи не означает, что назначение не выполнено. Ошибка локального
        журналирования не отменяет уже выполненную команду Journal.
    """
    student_id = form.cleaned_data["student_id"]
    class_id = form.cleaned_data["class_id"]
    targets = {"student_id": str(student_id), "class_id": class_id}
    try:
        result = journal.add_student_to_class(
            student_id, class_id, str(request.user.pk)
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        code = f"journal_http_{status}"
        message = {
            404: "Ученик или класс не найден. Обновите форму и проверьте данные.",
            409: "Ученик уже состоит в другом классе. Для перевода нужна отдельная операция.",
            422: "Пользователь должен быть активным учеником. Проверьте его данные.",
            503: "Journal временно недоступен. Проверьте текущий класс перед повторной отправкой.",
        }.get(status, "Journal отклонил служебный запрос. Обратитесь к администратору.")
        if status >= 500 and status != 503:
            message = "Journal вернул ошибку. Проверьте текущий класс перед повторной отправкой."
    except httpx.RequestError:
        code = "journal_result_unknown"
        message = "Не удалось получить результат от Journal. Проверьте текущий класс перед повторной отправкой."
    except JournalProtocolError:
        code = "journal_protocol_error"
        message = "Journal вернул некорректный ответ. Проверьте текущий класс перед повторной отправкой."
    else:
        AdminActionRecord.objects.create(
            actor=request.user,
            action="add_student_to_class",
            succeeded=True,
            target_ids={**targets, "period_id": result.period.id},
            result_code="created" if result.created else "already_exists",
        )
        if result.created:
            messages.success(request, "Ученик добавлен в класс.")
        else:
            messages.info(request, "Ученик уже состоит в этом классе.")
        return redirect("backoffice-add-student-to-class")
    form.add_error(None, message)
    AdminActionRecord.objects.create(
        actor=request.user,
        action="add_student_to_class",
        succeeded=False,
        target_ids=targets,
        result_code=code,
    )
    return None
