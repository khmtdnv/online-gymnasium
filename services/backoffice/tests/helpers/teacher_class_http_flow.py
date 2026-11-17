"""Одноразовая Django-проверка на настоящем тестовом Journal HTTP-сервере."""

import os
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parents[1] / "conftest.py"))

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from backoffice_admin.models import AdminActionRecord

settings.JOURNAL_BASE_URL = os.environ["TEACHER_TEST_JOURNAL_URL"]
settings.JOURNAL_SERVICE_TOKEN = "teacher-test-backoffice-token"
call_command("migrate", verbosity=0)
staff = get_user_model().objects.create_user(
    username="teacher-test-staff", is_staff=True
)
client = Client()
client.force_login(staff)
body = {
    "teacher_id": os.environ["TEACHER_TEST_ID"],
    "class_id": os.environ["TEACHER_TEST_CLASS"],
    "action": "assign",
}
url = "/admin/teacher-classes/"
assert client.post(url, body).status_code == 302
assert client.post(url, body).status_code == 302
assert list(
    AdminActionRecord.objects.order_by("id").values_list("result_code", flat=True)
) == ["created", "already_exists"]
page = client.get(url, {"teacher_id": body["teacher_id"]})
assert page.status_code == 200 and "7А" in page.content.decode()
assert client.post(url, {**body, "action": "remove"}).status_code == 302
assert client.post(url, {**body, "action": "remove"}).status_code == 302
assert AdminActionRecord.objects.count() == 4
assert (
    list(AdminActionRecord.objects.values_list("actor_id", flat=True)) == [staff.pk] * 4
)
print("Backoffice -> Journal -> Gateway flow OK")
