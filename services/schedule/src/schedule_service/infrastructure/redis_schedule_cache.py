import json
from datetime import date, datetime
from uuid import UUID

import redis.asyncio as redis

from schedule_service.domain.lesson import Lesson

_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""

_SET_IF_GENERATION_SCRIPT = """
local current = redis.call("GET", KEYS[2]) or "0"

if current ~= ARGV[1] then
    return 0
end

redis.call("SET", KEYS[1], ARGV[2], "EX", ARGV[3])
return 1
"""

_INVALIDATE_SCRIPT = """
redis.call("INCR", KEYS[2])
return redis.call("DEL", KEYS[1])
"""


class RedisScheduleCache:
    """Хранит дневное расписание и защищает заполнение кеша через Redis."""

    def __init__(self, client: redis.Redis) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            client: Настроенный клиент внешнего хранилища.
        """
        self._client = client

    def _key(self, *, class_id: int, day: date) -> str:
        """Строит ключ кеша расписания класса на день.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Ключ Redis для выбранного класса и дня.
        """
        return f"schedule:v2:class:{class_id}:date:{day.isoformat()}"

    def _generation_key(self, *, class_id: int, day: date) -> str:
        """Строит ключ счётчика поколения дневного кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Ключ Redis с суффиксом :gen.
        """
        return f"{self._key(class_id=class_id, day=day)}:gen"

    def _lock_key(self, *, class_id: int, day: date) -> str:
        """Строит ключ блокировки заполнения дневного кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Ключ Redis с суффиксом :lock.
        """
        return f"{self._key(class_id=class_id, day=day)}:lock"

    @staticmethod
    def _serialize(lessons: list[Lesson]) -> str:
        """Преобразует уроки в JSON, сохраняя даты в ISO-формате.

        Args:
            lessons: Уроки для сериализации или записи в кеш.

        Returns:
            JSON-строка списка уроков.
        """
        payload = []
        for lesson in lessons:
            payload.append(
                {
                    "id": lesson.id,
                    "class_id": lesson.class_id,
                    "teacher_id": str(lesson.teacher_id),
                    "subject_id": lesson.subject_id,
                    "starts_at": lesson.starts_at.isoformat(),
                    "ends_at": lesson.ends_at.isoformat(),
                    "status": lesson.status,
                    "version": lesson.version,
                }
            )

        return json.dumps(payload)

    @staticmethod
    def _deserialize(serialized: str) -> list[Lesson]:
        """Восстанавливает уроки и datetime из JSON кеша.

        Args:
            serialized: JSON со списком уроков из кеша.

        Returns:
            Список восстановленных уроков.
        """
        payload = json.loads(serialized)

        lessons = []
        for lesson in payload:
            lessons.append(
                Lesson(
                    id=lesson["id"],
                    class_id=lesson["class_id"],
                    teacher_id=UUID(lesson["teacher_id"]),
                    subject_id=lesson["subject_id"],
                    starts_at=datetime.fromisoformat(lesson["starts_at"]),
                    ends_at=datetime.fromisoformat(lesson["ends_at"]),
                    status=lesson["status"],
                    version=lesson["version"],
                )
            )

        return lessons

    async def get(self, *, class_id: int, day: date) -> list[Lesson] | None:
        """Читает дневное расписание из кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Список уроков, в том числе пустой; None означает отсутствие кеша.
        """
        serialized = await self._client.get(self._key(class_id=class_id, day=day))

        if serialized is None:
            return None

        return self._deserialize(serialized)

    async def get_generation(self, *, class_id: int, day: date) -> int:
        """Читает поколение дневного кеша расписания.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.

        Returns:
            Текущее поколение; 0, если ключ ещё не существует.
        """
        generation = await self._client.get(
            self._generation_key(class_id=class_id, day=day)
        )

        if generation is None:
            return 0

        return int(generation)

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
        result = await self._client.set(
            self._lock_key(class_id=class_id, day=day),
            token,
            nx=True,
            px=ttl_ms,
        )
        return result is True

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
        await self._client.eval(
            _RELEASE_LOCK_SCRIPT,
            1,
            self._lock_key(class_id=class_id, day=day),
            token,
        )

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
        result = await self._client.eval(
            _SET_IF_GENERATION_SCRIPT,
            2,
            self._key(class_id=class_id, day=day),
            self._generation_key(class_id=class_id, day=day),
            str(expected_generation),
            self._serialize(lessons),
            str(ttl_seconds),
        )
        return bool(result)

    async def invalidate(
        self,
        *,
        class_id: int,
        days: tuple[date, ...],
    ) -> None:
        """Повышает поколение и удаляет кеш каждого указанного дня.

        Для каждого дня повышение поколения и удаление атомарны. Повторная доставка
        безопасна для удаления кеша.

        Args:
            class_id: ID класса, для которого выполняется операция.
            days: Даты, кеш которых нужно удалить.
        """
        if not days:
            return

        for day in days:
            await self._client.eval(
                _INVALIDATE_SCRIPT,
                2,
                self._key(class_id=class_id, day=day),
                self._generation_key(class_id=class_id, day=day),
            )

    async def aclose(self) -> None:
        """Закрывает подключение клиента кеша."""
        await self._client.aclose()
