"""Контракт сохранения и чтения школьных классов."""

from typing import Protocol

from journal_service.domain.school_class import Class


class ClassRepository(Protocol):
    """Предоставляет операции со школьными классами в текущей транзакции."""

    async def get_class_by_id(self, class_id: int) -> Class | None:
        """Получает класс для проверки наличия перед чтением его состава.

        Args:
            class_id: ID класса в Journal.

        Returns:
            Сохранённый класс либо None, если запись отсутствует.
        """
        ...

    async def create_class(self, school_class: Class) -> Class:
        """Сохраняет класс без самостоятельного commit.

        Args:
            school_class: Данные нового класса.

        Returns:
            Сохранённый класс с ID и временем создания от базы данных.
        """
        ...

    async def list_classes(
        self, study_year: int | None, limit: int, offset: int
    ) -> list[Class]:
        """Читает страницу классов в порядке возрастания ID.

        Args:
            study_year: Учебный год; None отключает фильтр по году.
            limit: Максимальное количество классов в ответе.
            offset: Количество записей, пропускаемых перед выдачей.

        Returns:
            Список классов; при отсутствии записей пустой список.
        """
        ...
