"""Запись намерения отправки без сетевого запроса и самостоятельного commit."""

from typing import Protocol
from uuid import UUID

from homework_service.domain.homework import Homework
from homework_service.domain.homework_answer import HomeworkAnswer


class OutboxRepository(Protocol):
    """Использует ту же транзакцию, что и результат проверки работы."""

    async def add_review_event(
        self, homework: Homework, answer: HomeworkAnswer
    ) -> None:
        """Сохраняет только ссылки и проверенный результат, не содержимое ответа.

        Args:
            homework: Задание с историческим классом и предметом.
            answer: Уже сохранённая попытка с серверным временем проверки.
        """
        ...

    async def get_pending(self, *, limit: int) -> list[dict]:
        """Читает пачку конвертов, ожидающих отправки."""
        ...

    async def mark_published(self, event_id: UUID) -> None:
        """Сохраняет подтверждение отправки; завершение транзакции принадлежит UoW."""
        ...
