from schedule_service.application.ports.schedule_cache import ScheduleCache
from schedule_service.domain.events import ScheduleChanged


class CacheInvalidator:
    """Удаляет кеш затронутых дней по событию изменения расписания."""

    def __init__(self, cache: ScheduleCache) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            cache: Кеш дневного расписания.
        """
        self._cache = cache

    async def handle(self, event: ScheduleChanged) -> None:
        """Удаляет дневной кеш класса для дат из полученного события.

        Args:
            event: Событие с данными для обработки или отправки.
        """
        await self._cache.invalidate(class_id=event.class_id, days=event.affected_dates)
