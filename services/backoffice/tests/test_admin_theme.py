"""Проверяет оформление Admin без изменения прав и серверных форм."""

import re
from pathlib import Path

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url_name",
    ["admin:index", "backoffice-create-user", "backoffice-link-parent-student"],
)
def test_staff_pages_include_shared_theme_and_navigation(
    client, django_user_model, url_name
):
    """На серверных страницах есть стиль и ссылки, а не секрет клиента Gateway."""
    staff = django_user_model.objects.create_user(username="theme-staff", is_staff=True)
    client.force_login(staff)
    response = client.get(reverse(url_name))
    content = response.content.decode()
    assert response.status_code == 200
    assert "backoffice_admin/theme.css" in content
    assert 'href="/"' in content
    assert reverse("backoffice-create-user") in content
    assert "Вход для сотрудников" in content
    assert "test-service-token" not in content
    if url_name != "admin:index":
        assert "csrfmiddlewaretoken" in content
        assert 'label for="id_' in content


def test_login_has_theme_but_not_staff_actions(client):
    response = client.get(reverse("admin:login"))
    assert "backoffice_admin/theme.css" in response.content.decode()
    assert 'class="og-admin-nav"' not in response.content.decode()


def test_theme_tokens_match_frontend():
    service = Path(__file__).resolve().parents[1]
    css = service / "src/backoffice_admin/static/backoffice_admin/theme.css"
    frontend = service.parent / "frontend/app/styles/tokens.css"
    expected = dict(
        re.findall(r"--([\w-]+):\s*(#[a-fA-F0-9]{6});", frontend.read_text())
    )
    actual = dict(re.findall(r"--([\w-]+):\s*(#[a-fA-F0-9]{6});", css.read_text()))
    assert {name: actual[name] for name in expected} == expected


def test_audit_permissions_remain_read_only(django_user_model):
    request = RequestFactory().get("/admin/")
    request.user = django_user_model.objects.create_superuser(
        username="audit-theme-staff", password="test-only"
    )
    model_admin = admin.site._registry[AdminActionRecord]
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    assert model_admin.has_view_permission(request) is True
