"""Чтение периодов учеников через сессию SQLAlchemy."""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from journal_service.application.ports.errors import CurrentPeriodAlreadyExistsError
from journal_service.domain.student_class_period import StudentClassPeriod
from journal_service.infrastructure.models.student_class_period import (
    StudentClassPeriodRow,
)


class SqlAlchemyStudentClassPeriodRepository:
    """Читает и изменяет периоды в общей транзакции Unit of Work."""

    def __init__(self, session: AsyncSession) -> None:
        """Получает ту же сессию, которую используют другие репозитории UoW.

        Args:
            session: Сессия текущего Unit of Work, без самостоятельного commit.
        """
        self._session = session

    async def create_period(self, period: StudentClassPeriod) -> StudentClassPeriod:
        """Записывает открытый период без самостоятельного commit.

        Args:
            period: Ученик и класс; joined_at при переводе — серверная дата
                закрытия старого периода, иначе время вступления назначает БД.

        Returns:
            Новый доменный объект с серверными ID и joined_at, left_at=None.

        Raises:
            CurrentPeriodAlreadyExistsError: Нарушен индекс одного открытого периода.
            SQLAlchemyError: Другой сбой записи или чтения серверных полей.
        """
        row = StudentClassPeriodRow(
            student_id=period.student_id, class_id=period.class_id
        )
        if period.joined_at is not None:
            row.joined_at = period.joined_at
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            driver_error = exc.driver_exception
            if (
                getattr(driver_error, "sqlstate", None) == "23505"
                and getattr(driver_error, "constraint_name", None)
                == "student_class_periods_current_student_unique"
            ):
                raise CurrentPeriodAlreadyExistsError from exc
            raise
        await self._session.refresh(row)
        return StudentClassPeriod(
            student_id=row.student_id,
            class_id=row.class_id,
            id=row.id,
            joined_at=row.joined_at,
            left_at=row.left_at,
        )

    async def get_period_for_update(
        self, student_id: UUID, period_id: int
    ) -> StudentClassPeriod | None:
        """Блокирует конкретный период ученика до завершения транзакции.

        Закрытые периоды не исключаются: после ожидания блокировки обработчик
        должен увидеть закрытие и распознать устаревшую команду.

        Args:
            student_id: Владелец периода из команды.
            period_id: Ожидаемый ID периода из исходной формы.

        Returns:
            Период с актуальными полями либо None, если такая пара ID отсутствует.

        Raises:
            SQLAlchemyError: Чтение или получение блокировки не удалось.
        """
        statement = (
            select(StudentClassPeriodRow)
            .where(
                StudentClassPeriodRow.student_id == student_id,
                StudentClassPeriodRow.id == period_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        row = (await self._session.execute(statement)).scalar_one_or_none()

        if row is None:
            return None

        return StudentClassPeriod(
            student_id=row.student_id,
            class_id=row.class_id,
            id=row.id,
            joined_at=row.joined_at,
            left_at=row.left_at,
        )

    async def close_period(self, period_id: int) -> StudentClassPeriod | None:
        """Закрывает ещё открытый период текущим временем PostgreSQL.

        Args:
            period_id: ID периода, принадлежность которого проверил обработчик.

        Returns:
            Закрытый период с серверной датой либо None, если он отсутствует
            или уже закрыт. Повтор не изменяет ранее сохранённую дату.

        Raises:
            SQLAlchemyError: Изменение периода не удалось.
        """
        statement = (
            update(StudentClassPeriodRow)
            .where(
                StudentClassPeriodRow.id == period_id,
                StudentClassPeriodRow.left_at.is_(None),
            )
            .values(left_at=func.clock_timestamp())
            .returning(StudentClassPeriodRow)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        return StudentClassPeriod(
            student_id=row.student_id,
            class_id=row.class_id,
            id=row.id,
            joined_at=row.joined_at,
            left_at=row.left_at,
        )

    async def get_current_period_for_student(
        self, student_id: UUID
    ) -> StudentClassPeriod | None:
        """Читает открытый период ученика, не возвращая завершённую историю.

        Args:
            student_id: ID ученика из Gateway.

        Returns:
            Текущий период ученика либо None, если открытого периода нет.

        Raises:
            SQLAlchemyError: Запрос не выполнен или найдено несколько периодов.
        """
        stmt = select(StudentClassPeriodRow).where(
            StudentClassPeriodRow.student_id == student_id,
            StudentClassPeriodRow.left_at.is_(None),
        )

        result = await self._session.execute(stmt)

        row = result.scalar_one_or_none()

        if row is None:
            return None

        return StudentClassPeriod(
            student_id=row.student_id,
            class_id=row.class_id,
            id=row.id,
            joined_at=row.joined_at,
            left_at=row.left_at,
        )

    async def list_periods_for_student(
        self, student_id: UUID, limit: int, offset: int
    ) -> list[StudentClassPeriod]:
        """Читает страницу истории классов указанного ученика.

        Args:
            student_id: ID ученика из Gateway.
            limit: Максимальное число периодов в ответе.
            offset: Число пропускаемых периодов.

        Returns:
            Закрытые и открытые периоды от старых к новым, с ID для разрешения
            одинаковых дат; пустой список, если страница не содержит записей.

        Raises:
            SQLAlchemyError: Запрос к базе не выполнен.
        """
        stmt = (
            select(StudentClassPeriodRow)
            .where(StudentClassPeriodRow.student_id == student_id)
            .order_by(
                StudentClassPeriodRow.joined_at,
                StudentClassPeriodRow.id,
            )
            .limit(limit)
            .offset(offset)
        )

        rows = await self._session.scalars(stmt)

        periods = []

        for period in rows:
            periods.append(
                StudentClassPeriod(
                    student_id=period.student_id,
                    class_id=period.class_id,
                    id=period.id,
                    joined_at=period.joined_at,
                    left_at=period.left_at,
                )
            )

        return periods

    async def list_current_periods_for_class(
        self, class_id: int, limit: int, offset: int
    ) -> list[StudentClassPeriod]:
        """Читает страницу текущего состава класса, исключая закрытые периоды.

        Args:
            class_id: ID школьного класса в Journal.
            limit: Максимальное число периодов в ответе.
            offset: Число пропускаемых открытых периодов.

        Returns:
            Открытые периоды по возрастанию ID; пустой список, если записей
            на странице нет.

        Raises:
            SQLAlchemyError: Запрос к базе не выполнен.
        """
        stmt = (
            select(StudentClassPeriodRow)
            .where(
                StudentClassPeriodRow.class_id == class_id,
                StudentClassPeriodRow.left_at.is_(None),
            )
            .order_by(StudentClassPeriodRow.id)
            .limit(limit)
            .offset(offset)
        )

        rows = await self._session.scalars(stmt)

        current_periods = []

        for period in rows:
            current_periods.append(
                StudentClassPeriod(
                    student_id=period.student_id,
                    class_id=period.class_id,
                    id=period.id,
                    joined_at=period.joined_at,
                    left_at=period.left_at,
                )
            )

        return current_periods
