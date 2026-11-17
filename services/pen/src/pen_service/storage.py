"""Одна транзакция сохраняет пачку и продвигает последовательность страницы."""

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pen_service.contracts import SavedBatch, StrokeBatch


class Base(DeclarativeBase):
    """Метаданные только собственной БД Pen."""


class PenPageRow(Base):
    """Сериализует запись и ограничивает объём конкретной страницы ученика."""

    __tablename__ = "pen_pages"
    __table_args__ = (
        CheckConstraint(
            "lesson_id > 0 AND last_sequence BETWEEN 0 AND 4096 AND point_count BETWEEN 0 AND 20000",
            name="pen_page_limits",
        ),
    )
    lesson_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    point_count: Mapped[int] = mapped_column(Integer, default=0)


class PenBatchRow(Base):
    """Содержит штрих, но не личные данные и не credentials пользователя."""

    __tablename__ = "pen_batches"
    __table_args__ = (
        UniqueConstraint("batch_id", name="pen_batch_identity"),
        UniqueConstraint(
            "lesson_id", "student_id", "sequence", name="pen_page_sequence"
        ),
        ForeignKeyConstraint(
            ["lesson_id", "student_id"], ["pen_pages.lesson_id", "pen_pages.student_id"]
        ),
        CheckConstraint(
            "sequence BETWEEN 1 AND 4096", name="pen_batch_sequence_positive"
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(Uuid)
    lesson_id: Mapped[int] = mapped_column(Integer)
    student_id: Mapped[UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)


class PenConflictError(Exception):
    """Пачка уже имеет другое содержимое либо её порядок устарел."""


class PenPageFullError(Exception):
    """Страница достигла явно заданного предела сохранённых координат."""


def constraint_name(error: IntegrityError) -> str | None:
    """Извлекает имя PG-ограничения, не распознавая текст локализованной ошибки."""
    cause = getattr(error.orig, "driver_exception", None) or error.orig.__cause__
    return getattr(cause, "constraint_name", None)


class PenStore:
    """Открывает короткую сессию на операцию, не держит её во время WebSocket."""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self._sessions = sessions

    async def append(
        self, lesson_id: int, student_id: UUID, batch: StrokeBatch
    ) -> SavedBatch:
        """Фиксирует данные до возврата; повтор того же ID не создаёт строку.

        Args:
            lesson_id: Проверенный Gateway ID урока.
            student_id: Проверенный Gateway ID ученика.
            batch: Проверенные точки и порядковый номер.

        Returns:
            Уже зафиксированная пачка.

        Raises:
            PenConflictError: ID, содержимое или последовательность конфликтуют.
            PenPageFullError: Превышен объём страницы.
        """
        try:
            async with self._sessions() as session, session.begin():
                try:
                    async with session.begin_nested():
                        session.add(
                            PenPageRow(lesson_id=lesson_id, student_id=student_id)
                        )
                        await session.flush()
                except IntegrityError as exc:
                    if constraint_name(exc) != "pen_pages_pkey":
                        raise
                page = await session.scalar(
                    select(PenPageRow)
                    .where(
                        PenPageRow.lesson_id == lesson_id,
                        PenPageRow.student_id == student_id,
                    )
                    .with_for_update()
                )
                existing = await session.scalar(
                    select(PenBatchRow).where(PenBatchRow.batch_id == batch.batch_id)
                )
                payload = batch.model_dump(mode="json")
                if existing is not None:
                    if (
                        existing.lesson_id != lesson_id
                        or existing.student_id != student_id
                        or existing.payload != payload
                    ):
                        raise PenConflictError
                    return SavedBatch(**existing.payload, id=existing.id)
                if batch.sequence != page.last_sequence + 1:
                    raise PenConflictError
                if (
                    page.point_count + len(batch.points) > 20000
                    or page.last_sequence >= 4096
                ):
                    raise PenPageFullError
                row = PenBatchRow(
                    batch_id=batch.batch_id,
                    lesson_id=lesson_id,
                    student_id=student_id,
                    sequence=batch.sequence,
                    payload=payload,
                )
                session.add(row)
                page.last_sequence = batch.sequence
                page.point_count += len(batch.points)
                await session.flush()
                result = SavedBatch(**payload, id=row.id)
            return result
        except IntegrityError as exc:
            if constraint_name(exc) in {"pen_batch_identity", "pen_page_sequence"}:
                raise PenConflictError from exc
            raise

    async def history(
        self, lesson_id: int, student_id: UUID, *, after: int
    ) -> list[SavedBatch]:
        """Читает максимум100 пачек после sequence; клиент продолжает с последней."""
        async with self._sessions() as session:
            rows = await session.scalars(
                select(PenBatchRow)
                .where(
                    PenBatchRow.lesson_id == lesson_id,
                    PenBatchRow.student_id == student_id,
                    PenBatchRow.sequence > after,
                )
                .order_by(PenBatchRow.sequence)
                .limit(100)
            )
            return [SavedBatch(**row.payload, id=row.id) for row in rows]
