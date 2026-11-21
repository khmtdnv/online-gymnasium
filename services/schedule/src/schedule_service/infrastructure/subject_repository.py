"""Пакетное чтение названий и осторожное заполнение локального справочника."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schedule_service.domain.subject import Subject
from schedule_service.infrastructure.models.subject import SubjectRow


class SqlAlchemySubjectRepository:
    """Не выполняет commit самостоятельно и не перезаписывает известное имя."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_many(self, ids: list[int]) -> list[Subject]:
        """Читает существующие предметы одним запросом; пустой пакет без SQL."""
        if not ids:
            return []
        rows = await self._session.scalars(
            select(SubjectRow).where(SubjectRow.id.in_(ids)).order_by(SubjectRow.id)
        )
        return [Subject(id=row.id, name=row.name) for row in rows]

    async def list_all(self) -> list[Subject]:
        """Весь справочник предметов по возрастанию идентификатора."""
        rows = await self._session.scalars(select(SubjectRow).order_by(SubjectRow.id))
        return [Subject(id=row.id, name=row.name) for row in rows]

    async def set_name(self, subject: Subject) -> None:
        """Заполняет неизвестное имя, отклоняя конфликт с уже известным названием."""
        row = await self._session.scalar(
            select(SubjectRow).where(SubjectRow.id == subject.id).with_for_update()
        )
        if row is None:
            self._session.add(SubjectRow(id=subject.id, name=subject.name))
        elif row.name is not None and row.name != subject.name:
            raise ValueError("Existing subject name differs; no overwrite allowed")
        else:
            row.name = subject.name
        await self._session.flush()
