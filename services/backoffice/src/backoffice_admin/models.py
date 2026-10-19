from django.conf import settings
from django.db import models


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

    def __str__(self) -> str:
        """Возвращает действие и код результата для отображения записи.

        Returns:
            Краткое название записи административного действия.
        """
        return f"{self.action} ({self.result_code})"
