"""Проверяет оформление Admin без изменения прав и серверных форм.

Межсервисный контракт: применённые в theme.css значения равны светлой
палитре tokens.css портала; шрифты — локальные копии woff2 портала.
"""

import re
from pathlib import Path

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse

from backoffice_admin.models import AdminActionRecord

pytestmark = pytest.mark.django_db

SERVICE = Path(__file__).resolve().parents[1]
THEME_CSS = SERVICE / "src/backoffice_admin/static/backoffice_admin/theme.css"
TOKENS_CSS = SERVICE.parent / "frontend/app/styles/tokens.css"
BASE_SITE = SERVICE / "src/backoffice_admin/templates/admin/base_site.html"
FONTS_DIR = SERVICE / "src/backoffice_admin/static/backoffice_admin/fonts"
PORTAL_FONTS = SERVICE.parent / "frontend/public/fonts"
LOCAL_FONTS = (
    "manrope-cyrillic-wght-normal.woff2",
    "manrope-latin-wght-normal.woff2",
    "source-serif-4-cyrillic-400-normal.woff2",
    "source-serif-4-cyrillic-600-normal.woff2",
)


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


def _light_tokens(text: str) -> dict[str, str]:
    """Токены светлой палитры tokens.css: блок :root до [data-theme='dark'].

    Тёмная тема — только портал: значения блока [data-theme='dark']
    в сверку с Backoffice не попадают.
    """
    light = text.split("[data-theme", 1)[0]
    return {
        name: value.strip()
        for name, value in re.findall(r"--([\w-]+):\s*([^;]+);", light)
    }


def test_theme_tokens_match_frontend():
    """Каждый светлый токен tokens.css есть в theme.css с тем же значением."""
    expected = _light_tokens(TOKENS_CSS.read_text())
    actual = _light_tokens(THEME_CSS.read_text())
    assert expected, "tokens.css портала должен отдавать светлые токены"
    for name, value in expected.items():
        assert actual.get(name) == value, f"токен --{name} разошёлся с порталом"


def test_theme_has_no_dark_block_and_only_token_colors():
    """Тёмной темы в Backoffice нет; вне блока токенов своих HEX-цветов нет."""
    css = THEME_CSS.read_text()
    assert "data-theme" not in css
    allowed = {
        value.lower()
        for value in _light_tokens(TOKENS_CSS.read_text()).values()
        if value.startswith("#")
    }
    used = {match.lower() for match in re.findall(r"#[0-9a-fA-F]{3,8}\b", css)}
    assert used <= allowed, used - allowed


def test_theme_declares_local_portal_fonts():
    """Manrope и Source Serif 4 подключены локально; Georgia — только фоллбэк."""
    css = THEME_CSS.read_text()
    for name in LOCAL_FONTS:
        assert f"url('fonts/{name}')" in css
    assert "font-family: 'Source Serif 4'" in css
    assert css.lower().count("georgia") == 1
    assert "--font-serif: 'Source Serif 4', Georgia, serif" in css
    assert re.search(
        r"#content h1,\s*\.og-form-card h1\s*\{[^}]*font-family:\s*var\(--font-serif\)",
        css,
    ), "заголовки страниц должны идти Source Serif 4, а не Georgia"


@pytest.mark.parametrize("name", LOCAL_FONTS)
def test_theme_fonts_are_byte_copies_of_portal(name):
    """woff2 в static — побайтовая копия шрифтов портала (не CDN, не пересборка)."""
    local = FONTS_DIR / name
    assert local.is_file(), name
    assert local.read_bytes() == (PORTAL_FONTS / name).read_bytes(), name


def test_no_external_cdns_in_theme_or_base_site():
    """Внешних доменов (в том числе шрифтовых CDN) в теме и шаблоне нет."""
    for path in (THEME_CSS, BASE_SITE):
        assert not re.search(r"https?://", path.read_text()), path


def test_audit_permissions_remain_read_only(django_user_model):
    request = RequestFactory().get("/admin/")
    request.user = django_user_model.objects.create_superuser(
        username="audit-theme-staff", password="***"
    )
    model_admin = admin.site._registry[AdminActionRecord]
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    assert model_admin.has_view_permission(request) is True
