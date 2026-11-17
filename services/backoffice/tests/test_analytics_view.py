"""Отчёт доступен только суперпользователю Django."""

from datetime import date
from unittest.mock import patch

import httpx
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_analytics_requires_superuser_and_shows_report(client, django_user_model):
    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    admin = django_user_model.objects.create_superuser(username="admin", password="x")
    path = reverse("backoffice-analytics")
    client.force_login(staff)
    with patch("backoffice_admin.analytics_views.read_analytics") as read:
        assert client.get(path).status_code == 403
        read.assert_not_called()
    client.force_login(admin)
    with patch("backoffice_admin.analytics_views.read_analytics") as read:
        read.return_value = {
            "classes": [{"id": 7, "name": "7А", "study_year": 2026}],
            "progress": [
                {
                    "student_name": "Петров Иван",
                    "subject_name": "Математика",
                    "graded_count": 2,
                    "average_grade": 4.5,
                }
            ],
            "events": [],
        }
        response = client.get(
            path, {"class_id": 7, "date_from": "2026-10-01", "date_to": "2026-10-22"}
        )
        assert response.status_code == 200
        assert "Петров Иван" in response.content.decode()
        assert "Математика" in response.content.decode()


def test_analytics_reader_validates_gateway_responses(monkeypatch):
    """Собирает страницу через закрытый Gateway с серверным секретом."""
    from backoffice_admin import analytics_views

    real_client = httpx.Client

    def handler(request):
        assert request.headers["X-Backoffice-Service-Token"] == "test-service-token"
        path = request.url.path
        if path.endswith("/classes"):
            return httpx.Response(
                200, json=[{"id": 7, "name": "7А", "study_year": 2026}]
            )
        if path.endswith("/progress"):
            assert request.url.params["class_id"] == "7"
            return httpx.Response(
                200,
                json=[
                    {
                        "student_name": "Петров Иван",
                        "subject_name": "Математика",
                        "graded_count": 2,
                        "average_grade": 4.5,
                    }
                ],
            )
        assert path.endswith("/audit")
        assert request.url.params["offset"] == "50"
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        analytics_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    report = analytics_views.read_analytics(
        {
            "date_from": date(2026, 10, 1),
            "date_to": date(2026, 10, 22),
            "class_id": 7,
            "offset": 50,
        }
    )
    assert report["progress"][0].student_name == "Петров Иван"
    assert report["previous_offset"] == 0


def test_analytics_reader_offers_next_class_page(monkeypatch):
    """При большом числе классов следующие записи остаются доступны."""
    from backoffice_admin import analytics_views

    real_client = httpx.Client

    def handler(request):
        if request.url.path.endswith("/classes"):
            assert request.url.params["offset"] == "100"
            return httpx.Response(
                200,
                json=[
                    {"id": i, "name": f"{i}А", "study_year": 2026}
                    for i in range(101, 201)
                ],
            )
        return httpx.Response(200, json=[])

    monkeypatch.setattr(
        analytics_views.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    report = analytics_views.read_analytics(
        {
            "date_from": date(2026, 10, 1),
            "date_to": date(2026, 10, 22),
            "class_offset": 100,
        }
    )
    assert report["previous_class_offset"] == 0
    assert report["next_class_offset"] == 200


def test_unavailable_analytics_shows_error_without_exposing_details(
    client, django_user_model
):
    """Сбой Gateway виден пользователю, а служебный ответ остаётся скрытым."""
    admin = django_user_model.objects.create_superuser(username="admin", password="x")
    client.force_login(admin)
    with patch("backoffice_admin.analytics_views.read_analytics") as read:
        read.side_effect = httpx.ConnectError("private upstream address")
        response = client.get(reverse("backoffice-analytics"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Не удалось загрузить аналитику" in content
    assert "private upstream address" not in content
