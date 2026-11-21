"""SQL попыток: ограничения выбирают победителя, UoW завершает транзакцию."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from homework_service.application.ports.errors import HomeworkAnswerConflictError
from homework_service.domain.homework_answer import HomeworkAnswer
from homework_service.infrastructure.models.homework import HomeworkRow
from homework_service.infrastructure.models.homework_answer import HomeworkAnswerRow


class SqlAlchemyHomeworkAnswerRepository:
    """Работает только с собственной сессией Homework."""

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет сессию текущего Unit of Work."""
        self._session = session

    async def review_candidates(self, after_id: int, limit: int):
        """Читает последнюю попытку каждого ученика, не определяя права доступа."""
        ranked = select(
            HomeworkAnswerRow.id,
            func.row_number()
            .over(
                partition_by=(
                    HomeworkAnswerRow.homework_id,
                    HomeworkAnswerRow.student_id,
                ),
                order_by=HomeworkAnswerRow.attempt_number.desc(),
            )
            .label("position"),
        ).subquery()
        result = await self._session.execute(
            select(HomeworkAnswerRow, HomeworkRow)
            .join(HomeworkRow, HomeworkRow.id == HomeworkAnswerRow.homework_id)
            .join(ranked, ranked.c.id == HomeworkAnswerRow.id)
            .where(ranked.c.position == 1, HomeworkAnswerRow.id > after_id)
            .order_by(HomeworkAnswerRow.id)
            .limit(limit)
        )
        return [
            (
                self._to_domain(answer),
                homework.id,
                homework.issued_lesson_id,
                homework.class_id,
                homework.subject_id,
                homework.description,
            )
            for answer, homework in result
        ]

    async def get_by_id(
        self, answer_id: int, *, for_update: bool = False
    ) -> HomeworkAnswer | None:
        """Читает попытку и при необходимости блокирует до завершения UoW.

        Args:
            answer_id: ID конкретной попытки.
            for_update: Блокировка перед проверкой или фиксацией файла.

        Returns:
            Независимая доменная попытка либо None при отсутствии записи.
        """
        stmt = select(HomeworkAnswerRow).where(HomeworkAnswerRow.id == answer_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        row = await self._session.scalar(stmt)
        return self._to_domain(row) if row is not None else None

    async def get_by_key(
        self, homework_id: int, student_id: UUID, idempotency_key: str
    ) -> HomeworkAnswer | None:
        """Читает конкретную отправку без создания новой записи.

        Args:
            homework_id: ID задания.
            student_id: Автор отправки.
            idempotency_key: Постоянный ключ конкретного нажатия «Сдать».

        Returns:
            Ранее сохранённая попытка либо None для нового ключа.
        """
        row = await self._session.scalar(
            select(HomeworkAnswerRow).where(
                HomeworkAnswerRow.homework_id == homework_id,
                HomeworkAnswerRow.student_id == student_id,
                HomeworkAnswerRow.idempotency_key == idempotency_key,
            )
        )
        return self._to_domain(row) if row is not None else None

    async def get_latest(
        self, homework_id: int, student_id: UUID
    ) -> HomeworkAnswer | None:
        """Блокирует последнюю существующую попытку, а первый INSERT защищён unique.

        Args:
            homework_id: ID задания.
            student_id: Ученик, историю которого читаем.

        Returns:
            Последняя попытка либо None, если сдач ещё не было.
        """
        row = await self._session.scalar(
            select(HomeworkAnswerRow)
            .where(
                HomeworkAnswerRow.homework_id == homework_id,
                HomeworkAnswerRow.student_id == student_id,
            )
            .order_by(HomeworkAnswerRow.attempt_number.desc())
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._to_domain(row) if row is not None else None

    async def add(self, answer: HomeworkAnswer) -> HomeworkAnswer:
        """Вставляет попытку; распознаёт только известные конфликты сдачи.

        Args:
            answer: Новая доменная попытка, ещё без серверного ID/времени.

        Returns:
            Сохранённые поля после flush.

        Raises:
            HomeworkAnswerConflictError: Уже создана попытка/отправка/активная работа.
            IntegrityError: Иная ошибка целостности не маскируется конфликтом.
        """
        row = HomeworkAnswerRow(
            **{
                key: value
                for key, value in asdict(answer).items()
                if key not in ("id", "submitted_at")
            }
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            driver = getattr(exc.orig, "driver_exception", None) or getattr(
                exc.orig, "__cause__", None
            )
            if getattr(driver, "sqlstate", None) == "23505" and getattr(
                driver, "constraint_name", None
            ) in (
                "homework_answers_attempt_unique",
                "homework_answers_key_unique",
                "homework_answers_submitted_unique",
            ):
                raise HomeworkAnswerConflictError from exc
            raise
        return self._to_domain(row)

    async def save_review(self, answer: HomeworkAnswer) -> HomeworkAnswer:
        """Обновляет только поля результата уже заблокированного ответа.

        Args:
            answer: Попытка с проверенным решением преподавателя.

        Returns:
            Сохранённые поля после UPDATE; commit выполняет Unit of Work.
        """
        row = (
            await self._session.execute(
                update(HomeworkAnswerRow)
                .where(HomeworkAnswerRow.id == answer.id)
                .values(
                    status=answer.status,
                    grade=answer.grade,
                    teacher_comment=answer.teacher_comment,
                    reviewer_id=answer.reviewer_id,
                    reviewed_at=answer.reviewed_at,
                )
                .returning(HomeworkAnswerRow)
                .execution_options(synchronize_session=False, populate_existing=True)
            )
        ).scalar_one()
        return self._to_domain(row)

    async def list_answers(
        self,
        homework_id: int,
        student_id: UUID | None,
        limit: int,
        offset: int,
        *,
        latest_only: bool,
    ) -> list[HomeworkAnswer]:
        """Читает историю либо последнюю попытку каждого ученика, новыми вперёд.

        Args:
            homework_id: Задание, ответы которого разрешены обработчиком.
            student_id: Необязательный фильтр автора для чтения истории.
            limit: Максимальный размер страницы.
            offset: Число пропускаемых результатов.
            latest_only: Оставить одну последнюю попытку каждого ученика.

        Returns:
            Попытки по submitted_at DESC, id DESC; пустой список на пустой странице.
        """
        stmt = select(HomeworkAnswerRow).where(
            HomeworkAnswerRow.homework_id == homework_id
        )
        if student_id is not None:
            stmt = stmt.where(HomeworkAnswerRow.student_id == student_id)
        if latest_only:
            ranked = (
                select(
                    HomeworkAnswerRow.id,
                    func.row_number()
                    .over(
                        partition_by=HomeworkAnswerRow.student_id,
                        order_by=HomeworkAnswerRow.attempt_number.desc(),
                    )
                    .label("position"),
                )
                .where(HomeworkAnswerRow.homework_id == homework_id)
                .subquery()
            )
            stmt = stmt.where(
                HomeworkAnswerRow.id.in_(
                    select(ranked.c.id).where(ranked.c.position == 1)
                )
            )
        rows = await self._session.scalars(
            stmt.order_by(
                HomeworkAnswerRow.submitted_at.desc(), HomeworkAnswerRow.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: HomeworkAnswerRow) -> HomeworkAnswer:
        """Отделяет поля попытки от времени жизни ORM-сессии."""
        return HomeworkAnswer(
            **{
                field: getattr(row, field)
                for field in HomeworkAnswer.__dataclass_fields__
            }
        )
