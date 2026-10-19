from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from schedule_service.application.errors import IdempotencyKeyAlreadyExists
from schedule_service.application.ports.idempotency_repository import IdempotencyRecord
from schedule_service.domain.lesson import Lesson
from schedule_service.infrastructure.models.idempotency_request import (
    IdempotencyRequestRow,
)
from schedule_service.infrastructure.models.scheduled_lesson import ScheduledLessonRow


class SqlAlchemyIdempotencyRepository:
    """Резервирует ключи повторных запросов в текущей транзакции."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            session: Сессия текущей транзакции; commit остаётся за Unit of Work.
        """
        self._session = session

    async def claim(self, operation: str, key: str, request_hash: str) -> None:
        """Вставляет новый ключ, оставляя откат конфликтной транзакции UoW.

        Args:
            operation: Название операции, в рамках которой уникален ключ запроса.
            key: Ключ повторного запроса, переданный клиентом.
            request_hash: Хеш данных запроса для проверки совпадения повторов.

        Raises:
            IdempotencyKeyAlreadyExists: Нарушена уникальность пары операции и ключа.
            SQLAlchemyError: Другой сбой базы; не подменяется повтором запроса.
        """
        statement = insert(IdempotencyRequestRow).values(
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
        )
        try:
            await self._session.execute(statement)
        except IntegrityError as exc:
            # SQLAlchemy2.0: asyncpg-ошибка — причина исключения DBAPI-адаптера.
            driver_error = getattr(exc.orig, "__cause__", None) or exc.orig
            if (
                getattr(driver_error, "sqlstate", None) == "23505"
                and getattr(driver_error, "constraint_name", None)
                == "idempotency_requests_operation_key_unique"
            ):
                raise IdempotencyKeyAlreadyExists from exc
            raise

    async def get_by_key(self, operation: str, key: str) -> IdempotencyRecord | None:
        """Читает хеш попытки и текущее состояние связанного урока.

        Args:
            operation: Название операции, в рамках которой уникален ключ.
            key: Ключ повторяемой попытки.

        Returns:
            Найденная запись; None при отсутствии ключа. Если попытка не завершена,
            поле lesson равно None.

        Raises:
            SQLAlchemyError: Чтение базы не удалось.
        """
        statement = select(IdempotencyRequestRow).where(
            IdempotencyRequestRow.operation == operation,
            IdempotencyRequestRow.idempotency_key == key,
        )
        existing_record = await self._session.scalar(statement)
        if existing_record is None:
            return None

        if existing_record.lesson_id is None:
            return IdempotencyRecord(
                request_hash=existing_record.request_hash,
                lesson=None,
            )

        statement = select(ScheduledLessonRow).where(
            ScheduledLessonRow.id == existing_record.lesson_id
        )
        orm_lesson = await self._session.scalar(statement)
        assert orm_lesson is not None

        return IdempotencyRecord(
            request_hash=existing_record.request_hash,
            lesson=Lesson(
                id=orm_lesson.id,
                class_id=orm_lesson.class_id,
                teacher_id=orm_lesson.teacher_id,
                subject_id=orm_lesson.subject_id,
                starts_at=orm_lesson.starts_at,
                ends_at=orm_lesson.ends_at,
                status=orm_lesson.status,
                version=orm_lesson.version,
            ),
        )

    async def complete(self, operation: str, key: str, lesson: Lesson) -> None:
        """Связывает зарезервированный ключ запроса с созданным уроком.

        Args:
            operation: Название операции, в рамках которой уникален ключ запроса.
            key: Ключ повторного запроса, переданный клиентом.
            lesson: Урок с данными для операции.
        """
        assert lesson.id is not None
        statement = (
            update(IdempotencyRequestRow)
            .where(
                IdempotencyRequestRow.operation == operation,
                IdempotencyRequestRow.idempotency_key == key,
            )
            .values(lesson_id=lesson.id)
        )
        await self._session.execute(statement)
