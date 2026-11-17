from uuid import UUID, uuid4

from django.conf import settings
from django.db import models, router, transaction


class GatewayIdentity(models.Model):
    """Явная связь пользователя Gateway с существующим сотрудником Django."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    gateway_user_id = models.UUIDField(unique=True)

    class Meta:
        db_table = "backoffice_gateway_identities"


class AdminEventOutbox(models.Model):
    """Намерение отправки локального результата действия в центральный аудит."""

    event_id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    envelope = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "backoffice_event_outbox"
        indexes = (
            models.Index(
                fields=["created_at", "event_id"],
                condition=models.Q(published_at__isnull=True),
                name="admin_outbox_pending",
            ),
        )


class AdminActionRecord(models.Model):
    """Запись о действии сотрудника: кто выполнил, над чем и с каким результатом."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=64)
    succeeded = models.BooleanField()
    target_ids = models.JSONField(default=dict)
    result_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_action_records"

    def save(self, *args, **kwargs) -> None:
        """Сохраняет локальную запись и её событие вместе, но не удалённую команду.

        Повторное сохранение существующей записи не создаёт повторного события.
        bulk_create обходит этот метод и для журнала действий не используется.
        """
        creating = self._state.adding
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            super().save(*args, **kwargs)
            if not creating:
                return
            ids = {}
            for key, value in self.target_ids.items():
                if key not in {
                    "user_id",
                    "student_id",
                    "parent_id",
                    "teacher_id",
                    "class_id",
                    "period_id",
                    "previous_period_id",
                    "payment_id",
                }:
                    continue
                if type(value) is int and 0 < value <= 9223372036854775807:
                    ids[key] = value
                elif isinstance(value, str):
                    try:
                        ids[key] = str(UUID(value))
                    except ValueError:
                        if (
                            value.isascii()
                            and value.isdecimal()
                            and 0 < int(value) <= 9223372036854775807
                        ):
                            ids[key] = value
            event_id = uuid4()
            AdminEventOutbox.objects.using(using).create(
                event_id=event_id,
                envelope={
                    "event_id": str(event_id),
                    "event_source": "backoffice",
                    "event_type": "backoffice.action.recorded",
                    "schema_version": 1,
                    "occurred_at": self.created_at.isoformat(),
                    "request_id": None,
                    "actor": {"source": "backoffice", "id": str(self.actor_id)},
                    "payload": {
                        "record_id": self.pk,
                        "action": self.action,
                        "succeeded": self.succeeded,
                        "result_code": self.result_code,
                        "target_ids": ids,
                    },
                },
            )

    def __str__(self) -> str:
        """Возвращает действие и код результата для отображения записи.

        Returns:
            Краткое название записи административного действия.
        """
        return f"{self.action} ({self.result_code})"
