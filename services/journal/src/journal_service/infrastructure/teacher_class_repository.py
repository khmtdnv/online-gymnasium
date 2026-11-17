"""Хранение текущих связей преподаватель—класс через SQLAlchemy."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.application.ports.errors import TeacherAlreadyAssignedError
from journal_service.domain.school_class import Class
from journal_service.infrastructure.models.school_class import ClassRow
from journal_service.infrastructure.models.teacher_class import TeacherClassRow


class SqlAlchemyTeacherClassRepository:
    """Не завершает транзакции: commit/rollback выполняет Unit of Work."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию общей транзакции.

        Args:
            session: Сессия владельца Unit of Work.
        """
        self._session = session

    async def add(self, teacher_id: UUID, class_id: int) -> None:
        """Вставляет пару, распознавая только её именованный конфликт уникальности.

        Args:
            teacher_id: Проверенный UUID преподавателя.
            class_id: Проверенный ID класса.

        Raises:
            TeacherAlreadyAssignedError: Пара уже записана другой транзакцией.
            IntegrityError: Другое ограничение БД нарушено.
        """
        self._session.add(TeacherClassRow(teacher_id=teacher_id, class_id=class_id))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            driver = exc.driver_exception
            if (
                getattr(driver, "sqlstate", None) == "23505"
                and getattr(driver, "constraint_name", None) == "teacher_classes_pkey"
            ):
                raise TeacherAlreadyAssignedError from exc
            raise

    async def is_assigned(self, teacher_id: UUID, class_id: int) -> bool:
        """Проверяет наличие пары одним EXISTS-запросом.

        Args:
            teacher_id: UUID преподавателя.
            class_id: ID класса.

        Returns:
            Признак существования конкретного назначения.
        """
        return bool(
            await self._session.scalar(
                select(
                    select(TeacherClassRow)
                    .where(
                        TeacherClassRow.teacher_id == teacher_id,
                        TeacherClassRow.class_id == class_id,
                    )
                    .exists()
                )
            )
        )

    async def remove(self, teacher_id: UUID, class_id: int) -> bool:
        """Удаляет пару одним DELETE без предварительного чтения.

        Args:
            teacher_id: UUID преподавателя.
            class_id: ID класса.

        Returns:
            Признак фактического удаления.
        """
        result = await self._session.execute(
            delete(TeacherClassRow).where(
                TeacherClassRow.teacher_id == teacher_id,
                TeacherClassRow.class_id == class_id,
            )
        )
        return result.rowcount > 0

    async def list_classes_for_teacher(
        self, teacher_id: UUID, limit: int, offset: int
    ) -> list[Class]:
        """Читает классы преподавателя по возрастанию ID.

        Args:
            teacher_id: UUID преподавателя.
            limit: Максимальное число записей.
            offset: Число пропускаемых записей.

        Returns:
            Классы с сохранёнными серверными полями.
        """
        rows = await self._session.scalars(
            select(ClassRow)
            .join(TeacherClassRow, TeacherClassRow.class_id == ClassRow.id)
            .where(TeacherClassRow.teacher_id == teacher_id)
            .order_by(ClassRow.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            Class(
                id=row.id,
                name=row.name,
                study_year=row.study_year,
                created_at=row.created_at,
            )
            for row in rows
        ]
