"""Контракт проверки актуального назначения преподавателя."""

from typing import Protocol
from uuid import UUID


class JournalReader(Protocol):
    """Читает назначения у владельца, а не из асинхронной копии."""

    async def get_current_class_id(self, student_id: UUID) -> int | None:
        """Читает текущий класс; None только при подтверждённом отсутствии.

        Args:
            student_id: UUID ученика из Gateway.

        Returns:
            ID класса или None.

        Raises:
            OwnerLookupUnavailableError: Journal не позволил проверить период.
        """
        ...

    async def is_teacher_assigned(self, teacher_id: UUID, class_id: int) -> bool:
        """Проверяет одну пару преподаватель—класс.

        Args:
            teacher_id: Доверенный UUID преподавателя из Gateway.
            class_id: ID класса исходного урока.

        Returns:
            True для назначения; False только для подтверждённого отсутствия.

        Raises:
            OwnerLookupUnavailableError: Journal недоступен или нарушил контракт.
        """
        ...
