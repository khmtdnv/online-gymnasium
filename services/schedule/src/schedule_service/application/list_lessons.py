import asyncio
import secrets
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from schedule_service.application.errors import ScheduleCacheBusy
from schedule_service.application.ports.schedule_cache import ScheduleCache
from schedule_service.application.ports.unit_of_work import UnitOfWorkFactory
from schedule_service.domain.lesson import Lesson


class ListLessonsQuery(BaseModel):
    """Класс и день, для которых нужно получить расписание."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    class_id: int = Field(gt=0)
    day: date


class ListLessonsHandler:
    """Читает расписание через кеш с блокировкой заполнения и проверкой поколения."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        cache: ScheduleCache,
        schedule_cache_ttl_seconds: int,
        schedule_cache_lock_ttl_ms: int,
        schedule_cache_lock_retry_delay_ms: int,
        schedule_cache_lock_retry_limit: int,
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            uow_factory: Фабрика отдельной транзакции с её репозиториями.
            cache: Кеш дневного расписания.
            schedule_cache_ttl_seconds: Срок хранения дневного кеша в секундах.
            schedule_cache_lock_ttl_ms: Срок блокировки заполнения в миллисекундах.
            schedule_cache_lock_retry_delay_ms: Пауза между попытками в миллисекундах.
            schedule_cache_lock_retry_limit: Максимальное число попыток чтения и
                заполнения кеша.
        """
        self._uow_factory = uow_factory
        self._cache = cache
        self._schedule_cache_ttl_seconds = schedule_cache_ttl_seconds
        self._schedule_cache_lock_ttl_ms = schedule_cache_lock_ttl_ms
        self._schedule_cache_lock_retry_delay_ms = schedule_cache_lock_retry_delay_ms
        self._schedule_cache_lock_retry_limit = schedule_cache_lock_retry_limit

    async def _read_from_database(
        self,
        query: ListLessonsQuery,
    ) -> list[Lesson]:
        """Читает расписание в отдельной сессии базы данных.

        Args:
            query: Класс и дата запрашиваемого расписания.

        Returns:
            Плановые уроки класса на указанный день.
        """
        async with self._uow_factory() as uow:
            return await uow.lessons.get_class_schedule(
                class_id=query.class_id,
                day=query.day,
            )

    async def handle(self, query: ListLessonsQuery) -> list[Lesson]:
        """Получает расписание из кеша или заполняет его из базы.

        Блокировка ограничивает параллельное заполнение. Поколение запрещает запись
        данных после инвалидации.

        Args:
            query: Класс и дата запрашиваемого расписания.

        Returns:
            Плановые уроки класса на выбранный день.

        Raises:
            ScheduleCacheBusy: Попытки получить согласованные данные исчерпаны.
        """
        for _ in range(self._schedule_cache_lock_retry_limit):
            cached_lessons = await self._cache.get(
                class_id=query.class_id,
                day=query.day,
            )
            if cached_lessons is not None:
                return cached_lessons

            token = secrets.token_urlsafe(32)
            acquired = await self._cache.try_acquire_fill_lock(
                class_id=query.class_id,
                day=query.day,
                token=token,
                ttl_ms=self._schedule_cache_lock_ttl_ms,
            )
            if not acquired:
                await asyncio.sleep(self._schedule_cache_lock_retry_delay_ms / 1000)
                continue

            try:
                cached_lessons = await self._cache.get(
                    class_id=query.class_id,
                    day=query.day,
                )
                if cached_lessons is not None:
                    return cached_lessons

                generation = await self._cache.get_generation(
                    class_id=query.class_id,
                    day=query.day,
                )
                lessons = await self._read_from_database(query)

                stored = await self._cache.set_if_generation(
                    class_id=query.class_id,
                    day=query.day,
                    lessons=lessons,
                    ttl_seconds=self._schedule_cache_ttl_seconds,
                    expected_generation=generation,
                )
                if stored:
                    return lessons
            finally:
                await self._cache.release_fill_lock(
                    class_id=query.class_id,
                    day=query.day,
                    token=token,
                )

        raise ScheduleCacheBusy
