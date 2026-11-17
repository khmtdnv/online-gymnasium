"""Отдельный SQL-repository файлов ответа, с локальной связью к его заданию."""

from datetime import datetime

from sqlalchemy import DateTime, exists, func, literal, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from homework_service.application.homework_files import HomeworkFileInput
from homework_service.domain.homework_answer_file import HomeworkAnswerFile
from homework_service.infrastructure.models.homework_answer import HomeworkAnswerRow
from homework_service.infrastructure.models.homework_answer_file import (
    HomeworkAnswerFileRow,
)


class SqlAlchemyHomeworkAnswerFileRepository:
    """Не завершает транзакцию и не обращается к объектному хранилищу."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию текущего UoW."""
        self._session = session

    async def add_files(
        self, answer_id: int, files: list[HomeworkFileInput]
    ) -> list[HomeworkAnswerFile]:
        """Резервирует файлы в том же commit, что и сам ответ."""
        rows = [
            HomeworkAnswerFileRow(answer_id=answer_id, **file.model_dump())
            for file in files
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return (await self.list_for_answers([answer_id])).get(answer_id, [])

    async def list_for_answers(
        self, answer_ids: list[int]
    ) -> dict[int, list[HomeworkAnswerFile]]:
        """Одним join читает файлы страницы и homework_id их ответов."""
        if not answer_ids:
            return {}
        rows = await self._session.execute(
            select(HomeworkAnswerFileRow, HomeworkAnswerRow.homework_id)
            .join(
                HomeworkAnswerRow,
                HomeworkAnswerFileRow.answer_id == HomeworkAnswerRow.id,
            )
            .where(HomeworkAnswerFileRow.answer_id.in_(answer_ids))
            .order_by(HomeworkAnswerFileRow.id)
        )
        result = {}
        for row, homework_id in rows:
            result.setdefault(row.answer_id, []).append(
                self._to_domain(row, homework_id)
            )
        return result

    async def get_by_id(self, file_id: int) -> HomeworkAnswerFile | None:
        """Читает файл и родителя, не доверяя ID из внешнего запроса."""
        result = (
            await self._session.execute(
                select(HomeworkAnswerFileRow, HomeworkAnswerRow.homework_id)
                .join(
                    HomeworkAnswerRow,
                    HomeworkAnswerFileRow.answer_id == HomeworkAnswerRow.id,
                )
                .where(HomeworkAnswerFileRow.id == file_id)
            )
        ).one_or_none()
        return self._to_domain(*result) if result is not None else None

    async def has_pending(self, answer_id: int) -> bool:
        """Не разрешает оценить ответ с недогруженными вложениями."""
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        HomeworkAnswerFileRow.answer_id == answer_id,
                        HomeworkAnswerFileRow.upload_status == "pending",
                    )
                )
            )
        )

    async def mark_ready(
        self, file_id: int, storage_key: str, started_at: datetime
    ) -> HomeworkAnswerFile | None:
        """Выбирает один ключ, пока внешний сценарий удерживает блокировку ответа."""
        start = literal(started_at, type_=DateTime(timezone=True))
        row = (
            await self._session.execute(
                update(HomeworkAnswerFileRow)
                .where(
                    HomeworkAnswerFileRow.id == file_id,
                    HomeworkAnswerFileRow.upload_status == "pending",
                    start <= func.clock_timestamp(),
                    start > func.clock_timestamp() - text("INTERVAL '1 hour'"),
                )
                .values(upload_status="ready", storage_key=storage_key)
                .returning(HomeworkAnswerFileRow.id)
                .execution_options(synchronize_session=False)
            )
        ).scalar_one_or_none()
        return await self.get_by_id(row) if row is not None else None

    @staticmethod
    def _to_domain(row: HomeworkAnswerFileRow, homework_id: int) -> HomeworkAnswerFile:
        """Добавляет вычисленную локальным join ссылку на задание, без её дублирования."""
        return HomeworkAnswerFile(
            homework_id=homework_id,
            **{
                field: getattr(row, field)
                for field in HomeworkAnswerFile.__dataclass_fields__
                if field != "homework_id"
            },
        )
