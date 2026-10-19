from datetime import date
from typing import Protocol

from schedule_service.domain.lesson import Lesson


class ScheduleCache(Protocol):
    """Контракт кеша расписания с поколением и блокировкой заполнения."""

    async def get(self, *, class_id: int, day: date) -> list[Lesson] | None:
        """Читает дневное расписание из кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Список уроков, в том числе пустой; None означает отсутствие кеша.
        """
        ...

    async def get_generation(self, *, class_id: int, day: date) -> int:
        """Читает поколение дневного кеша расписания.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Текущее поколение; 0, если ключ ещё не существует.
        """
        ...

    async def try_acquire_fill_lock(
        self,
        *,
        class_id: int,
        day: date,
        token: str,
        ttl_ms: int,
    ) -> bool:
        """Пытается получить блокировку заполнения дневного кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.
            token: Уникальный токен владельца блокировки заполнения.
            ttl_ms: Срок действия блокировки в миллисекундах.

        Returns:
            True, если блокировка получена; False, если ключ уже занят.
        """
        ...

    async def release_fill_lock(
        self,
        *,
        class_id: int,
        day: date,
        token: str,
    ) -> None:
        """Удаляет блокировку только при совпадении токена владельца.

        Просроченный владелец не удалит блокировку, полученную другим запросом.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.
            token: Уникальный токен владельца блокировки заполнения.
        """
        ...

    async def set_if_generation(
        self,
        *,
        class_id: int,
        day: date,
        lessons: list[Lesson],
        ttl_seconds: int,
        expected_generation: int,
    ) -> bool:
        """Записывает расписание, только если поколение кеша не изменилось.

        Проверка поколения и запись выполняются одной атомарной операцией Redis.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.
            lessons: Уроки для сериализации или записи в кеш.
            ttl_seconds: Срок хранения кеша в секундах.
            expected_generation: Поколение кеша, прочитанное до запроса к базе.

        Returns:
            True, если данные записаны; False, если поколение уже другое.
        """
        ...

    async def invalidate(self, *, class_id: int, days: tuple[date, ...]) -> None:
        """Повышает поколение и удаляет кеш каждого указанного дня.

        Для каждого дня повышение поколения и удаление атомарны. Повторная доставка
        безопасна для удаления кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            days: Даты, кеш которых нужно удалить.
        """
        ...

    async def aclose(self) -> None:
        """Закрывает подключение клиента кеша."""
        ...
