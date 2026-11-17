"""Отчёт успеваемости и журнал событий для администратора Django."""

from datetime import timedelta

import httpx
from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from pydantic import BaseModel, TypeAdapter, ValidationError


class AnalyticsForm(forms.Form):
    """Проверяет период и выбранный класс до запроса к Gateway."""

    date_from = forms.DateField(
        label="С даты", widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        label="По дату", widget=forms.DateInput(attrs={"type": "date"})
    )
    class_id = forms.IntegerField(
        label="Класс", required=False, min_value=1, max_value=2147483647
    )
    offset = forms.IntegerField(required=False, min_value=0, max_value=2147483597)
    class_offset = forms.IntegerField(required=False, min_value=0, max_value=2147483547)

    def clean(self):
        """Ограничивает период тем же правилом, что и Gateway."""
        data = super().clean()
        first, last = data.get("date_from"), data.get("date_to")
        if first and last and not timedelta(0) <= last - first < timedelta(days=366):
            raise forms.ValidationError("Выберите период не более года.")
        return data


class ClassInfo(BaseModel):
    """Класс для выбора отчёта."""

    id: int
    name: str
    study_year: int


class ProgressInfo(BaseModel):
    """Показатели одного ученика по предмету."""

    student_name: str
    subject_name: str
    graded_count: int
    average_grade: float


class AuditInfo(BaseModel):
    """Читаемая часть события административного журнала."""

    occurred_at: str
    event_source: str
    event_type: str
    actor: dict
    payload: dict


def read_analytics(data: dict) -> dict:
    """Читает отчёт через служебный Gateway без передачи Django-cookie."""
    with httpx.Client(base_url=settings.GATEWAY_BASE_URL, timeout=10.0) as client:
        headers = {"X-Backoffice-Service-Token": settings.GATEWAY_SERVICE_TOKEN}

        def get(path, params, model):
            response = client.get(
                path, params=params, headers=headers, follow_redirects=False
            )
            response.raise_for_status()
            return TypeAdapter(list[model]).validate_json(response.content)

        prefix = "/internal/backoffice/analytics"
        class_offset = data.get("class_offset") or 0
        classes = get(f"{prefix}/classes", {"offset": class_offset}, ClassInfo)
        if len(classes) > 100:
            raise ValueError("Gateway returned too many classes")
        period = {
            "date_from": data["date_from"].isoformat(),
            "date_to": data["date_to"].isoformat(),
        }
        class_id = data.get("class_id") or (classes[0].id if classes else None)
        progress = (
            get(f"{prefix}/progress", {**period, "class_id": class_id}, ProgressInfo)
            if class_id
            else []
        )
        offset = data.get("offset") or 0
        events = get(
            f"{prefix}/audit", {**period, "limit": 50, "offset": offset}, AuditInfo
        )
        return {
            "classes": classes,
            "progress": progress,
            "events": events,
            "selected_class": class_id,
            "class_offset": class_offset,
            "previous_class_offset": max(0, class_offset - 100)
            if class_offset
            else None,
            "next_class_offset": class_offset + 100
            if len(classes) == 100 and class_offset + 100 <= 2147483547
            else None,
            "previous_offset": max(0, offset - 50) if offset else None,
            "next_offset": offset + 50
            if len(events) == 50 and offset + 50 <= 2147483597
            else None,
        }


@never_cache
@require_GET
def analytics_view(request: HttpRequest) -> HttpResponse:
    """Показывает отчёт только суперпользователю Backoffice."""
    if not request.user.is_superuser:
        raise PermissionDenied
    today = timezone.localdate()
    form = AnalyticsForm(
        request.GET or {"date_from": today - timedelta(days=30), "date_to": today}
    )
    report = None
    if form.is_valid():
        try:
            report = read_analytics(form.cleaned_data)
        except httpx.HTTPError, ValidationError, ValueError:
            form.add_error(None, "Не удалось загрузить аналитику. Попробуйте позже.")
    return render(
        request,
        "backoffice_admin/analytics.html",
        {
            **admin.site.each_context(request),
            "title": "Успеваемость и аудит",
            "form": form,
            "report": report,
        },
    )
