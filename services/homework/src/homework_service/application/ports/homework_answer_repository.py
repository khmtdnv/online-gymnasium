"""Хранение попыток внутри общей транзакции Homework."""

from typing import Protocol
from uuid import UUID

from homework_service.domain.homework_answer import HomeworkAnswer


class HomeworkAnswerRepository(Protocol):
    """Читает историю и сохраняет ответ/проверку без самостоятельного commit."""

    async def get_by_id(
        self, answer_id: int, *, for_update: bool = False
    ) -> HomeworkAnswer | None:
        """Возвращает попытку, при необходимости блокируя её до конца UoW."""
        ...

    async def get_by_key(
        self, homework_id: int, student_id: UUID, idempotency_key: str
    ) -> HomeworkAnswer | None:
        """Ищет результат конкретной отправки этого ученика."""
        ...

    async def get_latest(
        self, homework_id: int, student_id: UUID
    ) -> HomeworkAnswer | None:
        """Читает последнюю попытку ученика, блокируя существующую строку."""
        ...

    async def add(self, answer: HomeworkAnswer) -> HomeworkAnswer:
        """Вставляет новую попытку и получает её серверные ID/время."""
        ...

    async def save_review(self, answer: HomeworkAnswer) -> HomeworkAnswer:
        """Сохраняет проверку ранее заблокированной попытки."""
        ...

    async def list_answers(
        self,
        homework_id: int,
        student_id: UUID | None,
        limit: int,
        offset: int,
        *,
        latest_only: bool,
    ) -> list[HomeworkAnswer]:
        """Возвращает страницу последних работ либо историю одного ученика."""
        ...
