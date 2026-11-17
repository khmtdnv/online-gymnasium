"""Метаданные вложений внутри общей транзакции задания."""

from datetime import datetime
from typing import Protocol

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.domain.homework_file import HomeworkFile


class HomeworkFileRepository(Protocol):
    """Читает и резервирует вложения, не выполняя commit самостоятельно."""

    async def add_files(
        self, homework_id: int, files: list[HomeworkFileInput]
    ) -> list[HomeworkFile]:
        """Создаёт ожидаемые вложения указанного задания в порядке входа.

        Args:
            homework_id: ID задания той же транзакции.
            files: Проверенные описания выбранных файлов.

        Returns:
            Вложения с серверными ID и состоянием pending.
        """
        ...

    async def list_for_homeworks(
        self, homework_ids: list[int]
    ) -> dict[int, list[HomeworkFile]]:
        """Читает метаданные страницы одним запросом, в порядке ID файла.

        Args:
            homework_ids: ID уже разрешённых заданий.

        Returns:
            Вложения по ID задания; отсутствующие группы не включены.
        """
        ...

    async def get_by_id(self, file_id: int) -> HomeworkFile | None:
        """Читает вложение без проверки прав доступа.

        Args:
            file_id: ID ожидаемого или готового вложения.

        Returns:
            Вложение либо None.
        """
        ...

    async def get_current_time(self) -> datetime:
        """Читает время PostgreSQL для ограничения возраста попытки.

        Returns:
            Aware-время своей БД, не часы браузера или другого контейнера.
        """
        ...

    async def mark_ready(
        self, file_id: int, storage_key: str, started_at: datetime
    ) -> HomeworkFile | None:
        """Фиксирует один ключ только для pending и попытки моложе часа.

        Args:
            file_id: ID ожидаемого вложения.
            storage_key: Новый отдельный ключ успешной попытки.
            started_at: Время начала попытки, ранее прочитанное из PostgreSQL.

        Returns:
            Обновлённая запись либо None при проигрыше, истечении или отсутствии.
        """
        ...
