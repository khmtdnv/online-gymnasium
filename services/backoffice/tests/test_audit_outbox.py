"""Локальная запись действия и намерение отправки сохраняются атомарно."""

import pytest


@pytest.mark.django_db
def test_admin_record_creates_private_safe_event(django_user_model):
    from backoffice_admin.models import AdminActionRecord, AdminEventOutbox

    staff = django_user_model.objects.create_user(username="audit-staff")
    record = AdminActionRecord.objects.create(
        actor=staff,
        action="create_user",
        succeeded=False,
        result_code="request_error",
        target_ids={
            "user_id": "75ef34f4-2588-41b1-b41e-cbd058c6025c",
            "password": "must-not-leak",
        },
    )
    event = AdminEventOutbox.objects.get().envelope
    assert event["actor"] == {"source": "backoffice", "id": str(staff.pk)}
    assert event["payload"]["succeeded"] is False
    assert event["payload"]["result_code"] == "request_error"
    assert "password" not in event["payload"]["target_ids"]
    record.save()
    assert AdminEventOutbox.objects.count() == 1


@pytest.mark.django_db
def test_admin_record_rolls_back_if_event_cannot_be_saved(
    django_user_model, monkeypatch
):
    from backoffice_admin.models import AdminActionRecord, AdminEventOutbox

    staff = django_user_model.objects.create_user(username="audit-failure")

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(AdminEventOutbox, "save", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        AdminActionRecord.objects.create(
            actor=staff, action="create_user", succeeded=True
        )
    assert AdminActionRecord.objects.count() == 0
