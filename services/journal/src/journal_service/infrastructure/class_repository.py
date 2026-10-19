"""Сохранение и чтение классов через сессию SQLAlchemy."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.application.ports.errors import DuplicateClassError
from journal_service.domain.school_class import Class
from journal_service.infrastructure.models.school_class import ClassRow


class SqlAlchemyClassRepository:
    """Работает с классами, оставляя управление транзакцией UoW."""

    def __init__(self, session: AsyncSession) -> None:
        """Получает сессию текущей транзакции.

        Args:
            session: Сессия, созданная владельцем Unit of Work.
        """
        self._session = session

    async def get_class_by_id(self, class_id: int) -> Class | None:
        """Читает класс для различения пустого состава и отсутствующей записи.

        Args:
            class_id: ID школьного класса в Journal.

        Returns:
            Доменный класс либо None, если записи нет.

        Raises:
            SQLAlchemyError: Запрос к базе не выполнен.
        """
        statement = select(ClassRow).where(ClassRow.id == class_id)
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return Class(
            id=row.id,
            name=row.name,
            study_year=row.study_year,
            created_at=row.created_at,
        )

    async def create_class(self, school_class: Class) -> Class:
        """Записывает класс и возвращает серверные поля без commit.

        Args:
            school_class: Данные нового школьного класса.

        Returns:
            Класс с ID и временем создания, полученными из базы.

        Raises:
            SQLAlchemyError: Не удалось записать или перечитать строку.
        """
        row = ClassRow(name=school_class.name, study_year=school_class.study_year)

        self._session.add(row)

        try:
            await self._session.flush()
        except IntegrityError as exc:
            driver_error = exc.driver_exception

            if getattr(driver_error, "sqlstate", None) != "23505":
                raise

            if (
                getattr(driver_error, "constraint_name", None)
                != "classes_name_study_year_unique"
            ):
                raise

            raise DuplicateClassError from exc

        await self._session.refresh(row)

        return Class(
            id=row.id,
            name=row.name,
            study_year=row.study_year,
            created_at=row.created_at,
        )

    async def list_classes(
        self, study_year: int | None, limit: int, offset: int
    ) -> list[Class]:
        """Читает страницу классов, сохраняя порядок возрастания ID.

        Args:
            study_year: Год для фильтра; None выбирает все годы.
            limit: Максимальное число записей страницы.
            offset: Число записей, пропускаемых перед страницей.

        Returns:
            Доменные объекты классов; пустой список при отсутствии записей.

        Raises:
            SQLAlchemyError: Запрос к базе не выполнен.
        """
        statement = select(ClassRow)

        if study_year is not None:
            statement = statement.where(ClassRow.study_year == study_year)

        statement = statement.order_by(ClassRow.id).limit(limit).offset(offset)

        result = await self._session.execute(statement)
        rows = result.scalars().all()

        school_classes = []

        for school_class in rows:
            school_classes.append(
                Class(
                    id=school_class.id,
                    name=school_class.name,
                    study_year=school_class.study_year,
                    created_at=school_class.created_at,
                )
            )

        return school_classes
