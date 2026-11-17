from datetime import date
from typing import Protocol

from analytics_service.application.workload import ClassDailyWorkload


class WorkloadRepository(Protocol):
    """Контракт чтения готовой дневной нагрузки класса."""

    async def get(self, *, class_id: int, day: date) -> ClassDailyWorkload | None:
        """Читает рассчитанную нагрузку класса на выбранный день.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Дневная нагрузка или None, если расчётной строки нет.
        """
        ...
