import asyncio

from clickhouse_connect.driver import Client

from analytics_service.application.snapshot import LessonSnapshot

COLUMN_NAMES = [
    "event_id",
    "occurred_at",
    "lesson_id",
    "class_id",
    "teacher_id",
    "subject_id",
    "starts_at",
    "ends_at",
    "status",
    "version",
]


class ClickHouseSnapshotRepository:
    """Записывает состояния уроков в ClickHouse одним INSERT на пачку."""

    def __init__(self, client: Client) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            client: Настроенный клиент внешнего хранилища.
        """
        self._client = client

    async def add_many(self, snapshots: list[LessonSnapshot]) -> None:
        """Записывает пачку снимков уроков одним INSERT в ClickHouse.

        Пустую пачку пропускает. Синхронный запрос выполняет в другом потоке.

        Args:
            snapshots: Снимки уроков для записи одной пачкой.
        """
        if not snapshots:
            return

        rows = [
            [
                snapshot.event_id,
                snapshot.occurred_at,
                snapshot.lesson_id,
                snapshot.class_id,
                snapshot.teacher_id,
                snapshot.subject_id,
                snapshot.starts_at,
                snapshot.ends_at,
                snapshot.status,
                snapshot.version,
            ]
            for snapshot in snapshots
        ]

        await asyncio.to_thread(
            self._client.insert,
            "lesson_snapshots_v2",
            rows,
            column_names=COLUMN_NAMES,
        )
