"""Сохраняет событие в общей SQL-сессии проверки работы."""

from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from homework_service.application.events import (
    EventActor,
    ReviewedAnswerEvent,
    ReviewedAnswerPayload,
)
from homework_service.domain.homework import Homework
from homework_service.domain.homework_answer import HomeworkAnswer
from homework_service.infrastructure.models.outbox_event import HomeworkOutboxEventRow


class SqlAlchemyOutboxRepository:
    """Не публикует Kafka и не завершает чужую транзакцию."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_review_event(
        self, homework: Homework, answer: HomeworkAnswer
    ) -> None:
        """Записывает минимальный результат проверки с новым ID события.

        Args:
            homework: Задание, доступ к которому уже проверен.
            answer: Сохранённая проверка со всеми серверными полями.

        Raises:
            ValueError: Проверка не соответствует заданию или её поля неполны.
            SQLAlchemyError: Вставка не выполнена; весь UoW должен откатиться.
        """
        if homework.id != answer.homework_id:
            raise ValueError("Review does not belong to homework")
        event = ReviewedAnswerEvent(
            event_id=uuid4(),
            occurred_at=answer.reviewed_at,
            actor=EventActor(id=answer.reviewer_id),
            payload=ReviewedAnswerPayload(
                answer_id=answer.id,
                homework_id=homework.id,
                student_id=answer.student_id,
                class_id=homework.class_id,
                subject_id=homework.subject_id,
                teacher_id=answer.reviewer_id,
                status=answer.status,
                grade=answer.grade,
            ),
        )
        self._session.add(
            HomeworkOutboxEventRow(
                event_id=event.event_id,
                envelope=event.model_dump(mode="json"),
            )
        )
        await self._session.flush()

    async def get_pending(self, *, limit: int) -> list[dict]:
        """Читает ожидающие конверты; повторы relay различаются по event_id."""
        rows = await self._session.scalars(
            select(HomeworkOutboxEventRow.envelope)
            .where(HomeworkOutboxEventRow.published_at.is_(None))
            .order_by(
                HomeworkOutboxEventRow.created_at, HomeworkOutboxEventRow.event_id
            )
            .limit(limit)
        )
        return list(rows)

    async def mark_published(self, event_id: UUID) -> None:
        """Ставит дату после Kafka ack; повторная отметка безопасна."""
        await self._session.execute(
            update(HomeworkOutboxEventRow)
            .where(
                HomeworkOutboxEventRow.event_id == event_id,
                HomeworkOutboxEventRow.published_at.is_(None),
            )
            .values(published_at=func.clock_timestamp())
        )
