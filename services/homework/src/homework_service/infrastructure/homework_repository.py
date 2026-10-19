"""SQLAlchemy-хранилище с точным распознаванием дубликата урока."""

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from homework_service.application.ports.errors import HomeworkAlreadyExistsError
from homework_service.domain.homework import Homework
from homework_service.infrastructure.models.homework import HomeworkRow


class SqlAlchemyHomeworkRepository:
    """Использует сессию UoW, не завершает транзакцию."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию общей транзакции.

        Args:
            session: Сессия текущего Unit of Work.
        """
        self._session = session

    async def list_for_lesson(self, lesson_id: int) -> list[Homework]:
        """Читает задания по ссылкам урока выдачи или срока.

        Args:
            lesson_id: Проверенный ID доступного урока.

        Returns:
            Обе группы по created_at DESC,id DESC без скрытия ошибочных связей.
        """
        rows = (
            await self._session.scalars(
                select(HomeworkRow)
                .where(
                    or_(
                        HomeworkRow.issued_lesson_id == lesson_id,
                        HomeworkRow.due_lesson_id == lesson_id,
                    )
                )
                .order_by(HomeworkRow.created_at.desc(), HomeworkRow.id.desc())
            )
        ).all()
        return [self._to_domain(row) for row in rows]

    async def add(self, homework: Homework) -> Homework:
        """Вставляет задание и получает значения базы после flush.

        Args:
            homework: Доменное задание; ID и created_at назначает база.

        Returns:
            Новый доменный объект с серверными полями.

        Raises:
            HomeworkAlreadyExistsError: Сработал UNIQUE урока выдачи.
            IntegrityError: Нарушено другое ограничение.
        """
        row = HomeworkRow(
            issued_lesson_id=homework.issued_lesson_id,
            class_id=homework.class_id,
            subject_id=homework.subject_id,
            author_id=homework.author_id,
            description=homework.description,
            due_lesson_id=homework.due_lesson_id,
            manual_due_datetime=homework.manual_due_datetime,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            driver = exc.driver_exception
            if (
                getattr(driver, "sqlstate", None) == "23505"
                and getattr(driver, "constraint_name", None)
                == "homework_assignments_issued_lesson_unique"
            ):
                raise HomeworkAlreadyExistsError from exc
            raise
        return self._to_domain(row)

    async def get_by_id(self, id: int) -> Homework | None:
        """Читает задание по собственному ID.

        Args:
            id: ID задания.

        Returns:
            Задание либо None.
        """
        row = await self._session.scalar(
            select(HomeworkRow).where(HomeworkRow.id == id)
        )
        return self._to_domain(row) if row is not None else None

    async def list_for_class(
        self, class_id: int, limit: int, offset: int
    ) -> list[Homework]:
        """Фильтрует класс до пагинации, с ID как вторым ключом порядка.

        Args:
            class_id: Текущий класс из авторитетного ответа Journal.
            limit: Проверенный размер страницы.
            offset: Проверенное смещение.

        Returns:
            Задания по created_at DESC,id DESC.
        """
        statement = (
            select(HomeworkRow)
            .where(HomeworkRow.class_id == class_id)
            .order_by(HomeworkRow.created_at.desc(), HomeworkRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.scalars(statement)).all()
        return [self._to_domain(row) for row in rows]

    async def get_by_issued_lesson_id(self, id: int) -> Homework | None:
        """Читает единственное задание урока выдачи.

        Args:
            id: ID урока из Schedule.

        Returns:
            Задание либо None.
        """
        row = await self._session.scalar(
            select(HomeworkRow).where(HomeworkRow.issued_lesson_id == id)
        )
        return self._to_domain(row) if row is not None else None

    @staticmethod
    def _to_domain(row: HomeworkRow) -> Homework:
        """Отделяет доменный объект от жизненного цикла ORM-сессии.

        Args:
            row: Загруженная или сохранённая строка.

        Returns:
            Доменное задание со всеми сохранёнными полями.
        """
        return Homework(
            id=row.id,
            issued_lesson_id=row.issued_lesson_id,
            class_id=row.class_id,
            subject_id=row.subject_id,
            author_id=row.author_id,
            description=row.description,
            due_lesson_id=row.due_lesson_id,
            manual_due_datetime=row.manual_due_datetime,
            created_at=row.created_at,
        )
