"""Контракт локального справочника предметов."""

from typing import Protocol

from schedule_service.domain.subject import Subject


class SubjectRepository(Protocol):
    """Читает пакеты и заполняет неизвестные названия без commit."""

    async def get_many(self, ids: list[int]) -> list[Subject]: ...

    async def set_name(self, subject: Subject) -> None: ...
