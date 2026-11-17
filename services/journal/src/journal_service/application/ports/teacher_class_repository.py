"""Контракт хранения назначений преподавателя без доступа к Gateway."""

from typing import Protocol
from uuid import UUID

from journal_service.domain.school_class import Class


class TeacherClassRepository(Protocol):
    """Записывает и читает связи внутри транзакции владельца."""

    async def is_assigned(self, teacher_id: UUID, class_id: int) -> bool:
        """Проверяет конкретную пару без чтения всего списка назначений.

        Args:
            teacher_id: UUID преподавателя.
            class_id: ID класса.

        Returns:
            True только для существующей пары.
        """
        ...

    async def add(self, teacher_id: UUID, class_id: int) -> None:
        """Добавляет пару без commit.

        Args:
            teacher_id: UUID преподавателя из Gateway.
            class_id: ID класса Journal.

        Raises:
            TeacherAlreadyAssignedError: Такая пара уже существует.
        """
        ...

    async def remove(self, teacher_id: UUID, class_id: int) -> bool:
        """Удаляет только указанную пару и сообщает, была ли она.

        Args:
            teacher_id: UUID преподавателя.
            class_id: ID класса.

        Returns:
            True, если удалена запись; False, если её уже не было.
        """
        ...

    async def list_classes_for_teacher(
        self, teacher_id: UUID, limit: int, offset: int
    ) -> list[Class]:
        """Читает страницу классов в порядке ID.

        Args:
            teacher_id: UUID преподавателя.
            limit: Размер страницы.
            offset: Количество пропускаемых записей.

        Returns:
            Классы либо пустой список.
        """
        ...
