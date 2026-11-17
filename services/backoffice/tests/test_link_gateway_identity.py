from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def test_link_is_explicit_idempotent_and_does_not_replace_existing_account(
    django_user_model,
):
    from backoffice_admin.models import GatewayIdentity

    staff = django_user_model.objects.create_user(username="staff", is_staff=True)
    other = django_user_model.objects.create_user(username="other", is_staff=True)
    gateway_id = uuid4()
    call_command("link_gateway_identity", "staff", str(gateway_id), stdout=StringIO())
    call_command("link_gateway_identity", "staff", str(gateway_id), stdout=StringIO())
    assert GatewayIdentity.objects.get(user=staff).gateway_user_id == gateway_id
    with pytest.raises(CommandError):
        call_command("link_gateway_identity", "staff", str(uuid4()), stdout=StringIO())
    with pytest.raises(CommandError):
        call_command(
            "link_gateway_identity", "other", str(gateway_id), stdout=StringIO()
        )
    assert GatewayIdentity.objects.count() == 1
    assert not GatewayIdentity.objects.filter(user=other).exists()


def test_link_rejects_invalid_uuid_and_non_staff(django_user_model):
    django_user_model.objects.create_user(username="student", is_staff=False)
    with pytest.raises(CommandError):
        call_command(
            "link_gateway_identity", "student", str(uuid4()), stdout=StringIO()
        )
    with pytest.raises(CommandError):
        call_command("link_gateway_identity", "student", "invalid", stdout=StringIO())
