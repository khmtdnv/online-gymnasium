"""Явно связывает существующие учётные записи для общего входа."""

from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from backoffice_admin.models import GatewayIdentity


class Command(BaseCommand):
    """Не создаёт сотрудников и не заменяет ранее созданные связи."""

    help = "Связать сотрудника Django с UUID пользователя Gateway"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("gateway_user_id")

    def handle(self, *args, **options):
        """Создаёт связь только для активного сотрудника, если конфликтов нет."""
        try:
            gateway_id = UUID(options["gateway_user_id"])
        except ValueError as exc:
            raise CommandError("Некорректный UUID пользователя Gateway.") from exc
        try:
            with transaction.atomic():
                user = (
                    get_user_model()
                    .objects.select_for_update()
                    .filter(username=options["username"], is_active=True, is_staff=True)
                    .first()
                )
                if user is None:
                    raise CommandError("Активный сотрудник Django не найден.")
                existing = GatewayIdentity.objects.filter(user=user).first()
                if existing is not None:
                    if existing.gateway_user_id != gateway_id:
                        raise CommandError("Сотрудник уже связан с другим аккаунтом.")
                    self.stdout.write("Связь уже существует.")
                    return
                if GatewayIdentity.objects.filter(gateway_user_id=gateway_id).exists():
                    raise CommandError(
                        "Аккаунт Gateway уже связан с другим сотрудником."
                    )
                GatewayIdentity.objects.create(user=user, gateway_user_id=gateway_id)
        except IntegrityError as exc:
            raise CommandError("Связь конфликтует с существующей записью.") from exc
        self.stdout.write(
            "Связь создана. Права Gateway и Django проверяются при входе."
        )
