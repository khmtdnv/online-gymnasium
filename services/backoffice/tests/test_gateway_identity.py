from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

pytestmark = pytest.mark.django_db


def test_gateway_identity_must_be_unique_in_both_directions(django_user_model):
    from backoffice_admin.models import GatewayIdentity

    first = django_user_model.objects.create_user(username="first")
    second = django_user_model.objects.create_user(username="second")
    gateway_id = uuid4()
    GatewayIdentity.objects.create(user=first, gateway_user_id=gateway_id)

    with pytest.raises(IntegrityError), transaction.atomic():
        GatewayIdentity.objects.create(user=second, gateway_user_id=gateway_id)
    with pytest.raises(IntegrityError), transaction.atomic():
        GatewayIdentity.objects.create(user=first, gateway_user_id=uuid4())


def test_linked_django_user_cannot_be_deleted_implicitly(django_user_model):
    from backoffice_admin.models import GatewayIdentity

    user = django_user_model.objects.create_user(username="staff")
    GatewayIdentity.objects.create(user=user, gateway_user_id=uuid4())
    with pytest.raises(ProtectedError):
        user.delete()
