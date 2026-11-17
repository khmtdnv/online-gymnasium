"""Создаёт очередь аудита без копирования старых записей действий."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("backoffice_admin", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="AdminEventOutbox",
            fields=[
                (
                    "event_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("envelope", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "backoffice_event_outbox",
                "indexes": [
                    models.Index(
                        condition=models.Q(published_at__isnull=True),
                        fields=["created_at", "event_id"],
                        name="admin_outbox_pending",
                    )
                ],
            },
        )
    ]
