import asyncio
from datetime import UTC, date

from clickhouse_connect.driver import Client

from analytics_service.application.workload import ClassDailyWorkload


class ClickHouseWorkloadRepository:
    """Читает готовую нагрузку из ClickHouse, выполняя запрос в другом потоке."""

    def __init__(self, client: Client) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            client: Настроенный клиент внешнего хранилища.
        """
        self._client = client

    async def get(self, *, class_id: int, day: date) -> ClassDailyWorkload | None:
        """Читает рассчитанную нагрузку класса на выбранный день.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Дневная нагрузка или None, если расчётной строки нет.
        """
        result = await asyncio.to_thread(
            self._client.query,
            """
            SELECT
                class_id,
                day,
                planned_lessons_count,
                planned_minutes,
                refreshed_at
            FROM class_daily_workload_v2
            WHERE class_id = {class_id:UInt64}
              AND day = {day:Date}
            LIMIT 1
            """,
            parameters={
                "class_id": class_id,
                "day": day,
            },
        )

        if not result.result_rows:
            return None

        class_id, day, count, minutes, refreshed_at = result.result_rows[0]

        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)
        else:
            refreshed_at = refreshed_at.astimezone(UTC)

        return ClassDailyWorkload(
            class_id=class_id,
            day=day,
            planned_lessons_count=count,
            planned_minutes=minutes,
            refreshed_at=refreshed_at,
        )
