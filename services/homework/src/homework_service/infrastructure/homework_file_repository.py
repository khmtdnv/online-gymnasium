"""SQLAlchemy-репозиторий метаданных, не передающий байты и не делающий commit."""

from datetime import datetime

from sqlalchemy import DateTime, func, literal, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.domain.homework_file import HomeworkFile
from homework_service.infrastructure.models.homework_file import HomeworkFileRow


class SqlAlchemyHomeworkFileRepository:
    """Использует сессию общей транзакции ДЗ и его ожидаемых вложений."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию текущего Unit of Work.

        Args:
            session: Сессия общей транзакции.
        """
        self._session = session

    async def add_files(
        self, homework_id: int, files: list[HomeworkFileInput]
    ) -> list[HomeworkFile]:
        """Резервирует места для файлов до получения байтов.

        Args:
            homework_id: ID сохранённого в текущей транзакции задания.
            files: Проверенные описания в порядке выбора.

        Returns:
            Новые pending-вложения с ID базы.
        """
        rows = [
            HomeworkFileRow(homework_id=homework_id, **file.model_dump())
            for file in files
        ]
        self._session.add_all(rows)
        if rows:
            await self._session.flush()
        return [self._to_domain(row) for row in rows]

    async def list_for_homeworks(
        self, homework_ids: list[int]
    ) -> dict[int, list[HomeworkFile]]:
        """Читает файлы всех заданий страницы одним SQL-запросом.

        Args:
            homework_ids: ID доступных заданий.

        Returns:
            Группы вложений, отсортированных по ID.
        """
        if not homework_ids:
            return {}
        rows = await self._session.scalars(
            select(HomeworkFileRow)
            .where(HomeworkFileRow.homework_id.in_(homework_ids))
            .order_by(HomeworkFileRow.id)
        )
        grouped: dict[int, list[HomeworkFile]] = {}
        for row in rows:
            grouped.setdefault(row.homework_id, []).append(self._to_domain(row))
        return grouped

    async def get_by_id(self, file_id: int) -> HomeworkFile | None:
        """Читает метаданные без авторизации пользователя.

        Args:
            file_id: ID вложения.

        Returns:
            Вложение либо None.
        """
        row = await self._session.scalar(
            select(HomeworkFileRow).where(HomeworkFileRow.id == file_id)
        )
        return self._to_domain(row) if row is not None else None

    async def get_current_time(self) -> datetime:
        """Возвращает часы PostgreSQL, чтобы проверка возраста не зависела от API.

        Returns:
            Текущее aware-время своей БД.

        Raises:
            OSError: БД вернула неожиданный результат вместо времени.
        """
        now = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise OSError("Database time unavailable")
        return now

    async def mark_ready(
        self, file_id: int, storage_key: str, started_at: datetime
    ) -> HomeworkFile | None:
        """Условный UPDATE выбирает победителя без отдельного SELECT FOR UPDATE.

        Args:
            file_id: ID ожидаемого вложения.
            storage_key: Отдельный ключ попытки, байты которой уже проверены.
            started_at: Время из PostgreSQL до передачи байтов.

        Returns:
            Новый ready либо None; существующий ready не изменяется.
        """
        start = literal(started_at, type_=DateTime(timezone=True))
        statement = (
            update(HomeworkFileRow)
            .where(
                HomeworkFileRow.id == file_id,
                HomeworkFileRow.upload_status == "pending",
                start <= func.clock_timestamp(),
                start > func.clock_timestamp() - text("INTERVAL '1 hour'"),
            )
            .values(upload_status="ready", storage_key=storage_key)
            .returning(HomeworkFileRow)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    @staticmethod
    def _to_domain(row: HomeworkFileRow) -> HomeworkFile:
        """Отделяет состояние вложения от ORM-сессии.

        Args:
            row: Загруженные поля строки файла.

        Returns:
            Проверенная доменная запись.
        """
        return HomeworkFile(
            id=row.id,
            homework_id=row.homework_id,
            file_name=row.file_name,
            size_bytes=row.size_bytes,
            content_type=row.content_type,
            content_sha256=row.content_sha256,
            upload_status=row.upload_status,
            storage_key=row.storage_key,
        )
