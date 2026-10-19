"""Доступ к заданиям в пределах локальной транзакции."""

from typing import Protocol

from homework_service.domain.homework import Homework


class HomeworkRepository(Protocol):
    """Хранит ДЗ, не выполняя commit самостоятельно."""

    async def list_for_lesson(self, lesson_id: int) -> list[Homework]:
        """Читает задания к уроку и из урока по created_at DESC,id DESC.

        Args:
            lesson_id: Проверенный ID урока Schedule.

        Returns:
            Обе группы, включая строки для проверки совместимости ссылок.
        """
        ...

    async def list_for_class(
        self, class_id: int, limit: int, offset: int
    ) -> list[Homework]:
        """Читает страницу класса по created_at DESC,id DESC.

        Args:
            class_id: Подтверждённый Journal текущий класс.
            limit: Размер страницы.
            offset: Число пропускаемых записей.

        Returns:
            Задания в порядке от новых к старым.
        """
        ...

    async def add(self, homework: Homework) -> Homework:
        """Сохраняет задание и получает серверные поля.

        Args:
            homework: Проверенное задание без ID.

        Returns:
            Сохранённое задание с ID и временем создания.

        Raises:
            HomeworkAlreadyExistsError: Задание урока уже существует.
        """
        ...

    async def get_by_id(self, id: int) -> Homework | None:
        """Читает задание по его ID.

        Args:
            id: ID задания в Homework.

        Returns:
            Задание либо None.
        """
        ...

    async def get_by_issued_lesson_id(self, id: int) -> Homework | None:
        """Читает задание урока выдачи.

        Args:
            id: ID урока из Schedule.

        Returns:
            Задание либо None.
        """
        ...
