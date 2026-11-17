"""Просмотр финансовой истории в административной панели."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from backoffice_admin.models import AdminActionRecord

STATUS_LABELS = {
    "creating": "Создаётся",
    "pending": "Ожидает оплаты",
    "succeeded": "Оплачен",
    "canceled": "Отменён",
    "unknown": "Статус неизвестен",
    "manual_review": "Нужна проверка",
    "refunded": "Возвращён",
}
REFUND_STATUS_LABELS = {
    "creating": "Создаётся",
    "pending": "Ожидает возврата",
    "succeeded": "Возврат выполнен",
    "canceled": "Возврат отменён",
    "unknown": "Статус возврата неизвестен",
    "manual_review": "Нужна проверка возврата",
}


class PaymentPageForm(forms.Form):
    """Ограничивает смещение страницы истории."""

    offset = forms.IntegerField(required=False, min_value=0, max_value=2147483597)


class RefundForm(forms.Form):
    """Подтверждает возврат учётной записью администратора Gateway."""

    email = forms.EmailField(label="Email администратора портала")
    password = forms.CharField(
        label="Пароль администратора портала", widget=forms.PasswordInput
    )
    confirm = forms.BooleanField(label="Подтверждаю полный возврат платежа")


class ReconcileForm(RefundForm):
    """Подтверждает сверку по ID платежа из кабинета провайдера."""

    confirm = forms.BooleanField(label="Подтверждаю проверку платежа")
    provider_id = forms.UUIDField(label="ID платежа в ЮKassa")


class GatewayAdmin(BaseModel):
    """Идентификатор подтверждённого администратора портала."""

    id: UUID
    role: Literal["admin"]


class GatewayLogin(BaseModel):
    """Короткоживущий токен, не сохраняемый между запросами."""

    access_token: str = Field(min_length=1, max_length=4096)


class GatewayRefund(BaseModel):
    """Проверенный ответ о принятой попытке возврата."""

    id: int = Field(strict=True, ge=1)
    status: Literal[
        "creating",
        "pending",
        "succeeded",
        "canceled",
        "unknown",
        "manual_review",
        "refunded",
    ]
    refund_status: (
        Literal[
            "creating", "pending", "succeeded", "canceled", "unknown", "manual_review"
        ]
        | None
    )


class PaymentInfo(BaseModel):
    """Только данные платежа, необходимые для таблицы Backoffice."""

    id: int = Field(strict=True, ge=1)
    student_name: str = Field(min_length=1)
    study_month: date
    amount_kopecks: int = Field(strict=True, ge=0)
    status: Literal[
        "creating",
        "pending",
        "succeeded",
        "canceled",
        "unknown",
        "manual_review",
        "refunded",
    ]
    refund_status: (
        Literal[
            "creating", "pending", "succeeded", "canceled", "unknown", "manual_review"
        ]
        | None
    )

    @property
    def amount_rubles(self) -> str:
        """Преобразует целые копейки в строку рублей без ошибок float."""
        return f"{Decimal(self.amount_kopecks) / 100:.2f}"

    @property
    def status_label(self) -> str:
        """Переводит статус платежа для сотрудника."""
        return STATUS_LABELS[self.status]

    @property
    def refund_status_label(self) -> str:
        """Переводит статус возврата или показывает его отсутствие."""
        return REFUND_STATUS_LABELS[self.refund_status] if self.refund_status else "—"

    @property
    def refund_action_label(self) -> str:
        """Оставляет повтор доступным при неполученном результате."""
        if self.status != "succeeded":
            return ""
        if self.refund_status is None:
            return "Вернуть платёж"
        if self.refund_status in {"creating", "pending", "unknown"}:
            return "Повторить запрос возврата"
        return ""


def read_payments(offset: int) -> dict:
    """Читает одну страницу через Gateway с проверкой ответа."""
    with httpx.Client(base_url=settings.GATEWAY_BASE_URL, timeout=10.0) as client:
        response = client.get(
            "/internal/backoffice/billing/payments",
            params={"offset": offset},
            headers={"X-Backoffice-Service-Token": settings.GATEWAY_SERVICE_TOKEN},
            follow_redirects=False,
        )
        response.raise_for_status()
        payments = TypeAdapter(list[PaymentInfo]).validate_json(response.content)
    if len(payments) > 50:
        raise ValueError("Gateway returned too many payments")
    return {
        "payments": payments,
        "previous_offset": max(0, offset - 50) if offset else None,
        "next_offset": offset + 50
        if len(payments) == 50 and offset + 50 <= 2147483597
        else None,
    }


@never_cache
@require_GET
def billing_view(request: HttpRequest) -> HttpResponse:
    """Показывает финансовую историю только суперпользователю Django."""
    if not request.user.is_superuser:
        raise PermissionDenied
    form = PaymentPageForm(request.GET)
    report = None
    if form.is_valid():
        try:
            report = read_payments(form.cleaned_data.get("offset") or 0)
        except httpx.HTTPError, ValidationError, ValueError:
            form.add_error(None, "Не удалось загрузить платежи. Попробуйте позже.")
    return render(
        request,
        "backoffice_admin/billing.html",
        {
            **admin.site.each_context(request),
            "title": "История платежей",
            "form": form,
            "report": report,
        },
    )


def financial_action_view(
    request: HttpRequest, payment_id: int, action: Literal["refund", "reconcile"]
) -> HttpResponse:
    """Подтверждает администратора и отправляет финансовую команду Gateway."""
    if not request.user.is_superuser:
        raise PermissionDenied
    if not 1 <= payment_id <= 2147483647:
        raise Http404
    form_type = RefundForm if action == "refund" else ReconcileForm
    action_name = "refund_payment" if action == "refund" else "reconcile_payment"
    form = form_type(request.POST or None)
    if request.method == "POST" and form.is_valid():
        origin = f"{request.scheme}://{request.get_host()}"
        refresh_cookie = None
        target_ids = None
        try:
            with httpx.Client(
                base_url=settings.GATEWAY_BASE_URL, timeout=10.0
            ) as client:
                try:
                    login = client.post(
                        "/api/v1/auth/login",
                        headers={"Origin": origin},
                        json={
                            "email": form.cleaned_data["email"],
                            "password": form.cleaned_data["password"],
                        },
                        follow_redirects=False,
                    )
                    login.raise_for_status()
                    refresh_cookie = login.cookies.get("refresh_token")
                    token = GatewayLogin.model_validate_json(login.content).access_token
                    if not refresh_cookie:
                        raise ValueError("Invalid login response")
                    headers = {"Authorization": f"Bearer {token}"}
                    profile = client.get(
                        "/api/v1/auth/me", headers=headers, follow_redirects=False
                    )
                    profile.raise_for_status()
                    gateway_admin = GatewayAdmin.model_validate_json(profile.content)
                    target_ids = {
                        "payment_id": payment_id,
                        "user_id": str(gateway_admin.id),
                    }
                    AdminActionRecord.objects.create(
                        actor=request.user,
                        action=action_name,
                        succeeded=False,
                        target_ids=target_ids,
                        result_code="request_started",
                    )
                    if action == "refund":
                        request_key = uuid5(
                            NAMESPACE_URL,
                            f"og:backoffice:refund:{request.user.pk}:{payment_id}",
                        )
                        body = {"request_key": str(request_key)}
                    else:
                        provider_id = form.cleaned_data.get("provider_id")
                        body = {
                            "provider_id": str(provider_id) if provider_id else None
                        }
                    response = client.post(
                        f"/api/v1/billing/payments/{payment_id}/{action}",
                        headers=headers,
                        json=body,
                        timeout=70.0,
                        follow_redirects=False,
                    )
                    response.raise_for_status()
                    result = GatewayRefund.model_validate_json(response.content)
                    if (
                        response.status_code != (202 if action == "refund" else 200)
                        or result.id != payment_id
                        or (action == "refund" and result.refund_status is None)
                    ):
                        raise ValueError("Invalid refund response")
                    AdminActionRecord.objects.create(
                        actor=request.user,
                        action=action_name,
                        succeeded=True,
                        target_ids=target_ids,
                        result_code="request_accepted",
                    )
                    messages.success(
                        request,
                        "Запрос выполнен. Проверьте итоговый статус платежа.",
                    )
                    return redirect("backoffice-billing")
                finally:
                    if refresh_cookie:
                        try:
                            logout = client.post(
                                "/api/v1/auth/logout",
                                headers={
                                    "Origin": origin,
                                    "Cookie": f"refresh_token={refresh_cookie}",
                                },
                                follow_redirects=False,
                            )
                            if logout.status_code != 204:
                                raise ValueError("Logout not confirmed")
                        except httpx.HTTPError, ValueError:
                            messages.warning(
                                request,
                                "Отзыв временной сессии портала не подтверждён.",
                            )
        except httpx.HTTPError, ValidationError, ValueError, KeyError:
            if target_ids is not None:
                AdminActionRecord.objects.create(
                    actor=request.user,
                    action=action_name,
                    succeeded=False,
                    target_ids=target_ids,
                    result_code="result_unknown",
                )
            form.add_error(
                None,
                "Не удалось подтвердить результат. Проверьте данные и статус платежа; повтор безопасен.",
            )
    return render(
        request,
        "backoffice_admin/refund.html",
        {
            **admin.site.each_context(request),
            "title": "Подтверждение возврата"
            if action == "refund"
            else "Проверка платежа",
            "form": form,
            "payment_id": payment_id,
            "action": action,
        },
    )


@never_cache
@require_http_methods(["GET", "POST"])
def refund_view(request: HttpRequest, payment_id: int) -> HttpResponse:
    """Инициирует полный возврат после подтверждения администратора Gateway."""
    return financial_action_view(request, payment_id, "refund")


@never_cache
@require_http_methods(["GET", "POST"])
def reconcile_view(request: HttpRequest, payment_id: int) -> HttpResponse:
    """Запрашивает проверку статуса платежа у провайдера."""
    return financial_action_view(request, payment_id, "reconcile")
