from django.contrib import admin

from backoffice_admin.models import AdminActionRecord

admin.site.index_template = "backoffice_admin/index.html"


@admin.register(AdminActionRecord)
class AdminActionRecordAdmin(admin.ModelAdmin):
    """Показывает журнал действий сотрудников без возможности редактирования."""

    list_display = ("created_at", "actor", "action", "succeeded", "result_code")
    list_filter = ("action", "succeeded")
    search_fields = ("actor__username", "result_code")
    ordering = ("-created_at",)
    readonly_fields = (
        "actor",
        "action",
        "succeeded",
        "target_ids",
        "result_code",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        """Запрещает добавлять записи журнала через админку."""
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        """Запрещает изменять записи журнала через админку."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Запрещает удалять записи журнала через админку."""
        return False
