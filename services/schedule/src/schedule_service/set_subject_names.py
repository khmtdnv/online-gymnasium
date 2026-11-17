"""Локальная операторская команда: заполнить подтверждённые названия предметов.

JSON со subjects и allowed_teacher_ids передаётся через stdin. Названия не
перезаписываются, если уже заполнены иначе; чужие уроки блокируют демо-настройку.
"""

import asyncio
import sys
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from schedule_service.config import Settings
from schedule_service.domain.subject import Subject
from schedule_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from schedule_service.infrastructure.models.scheduled_lesson import ScheduledLessonRow


class SubjectNameInput(BaseModel):
    """Явно заданный ID и непустое проверенное название."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(strict=True, ge=1, le=2147483647)
    name: str = Field(strict=True, min_length=1, max_length=100)


class SubjectNamesInput(BaseModel):
    """Ограниченный пакет и разрешённые UUID преподавателей демо-набора."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    subjects: list[SubjectNameInput] = Field(min_length=1, max_length=1000)
    allowed_teacher_ids: list[UUID] = Field(min_length=1, max_length=1000)


async def set_subject_names(data: SubjectNamesInput) -> None:
    """Заполняет только неизвестные названия одной атомарной транзакцией.

    Args:
        data: Проверенные названия и список доверенных демо-преподавателей.

    Raises:
        ValueError: Конфликт названия, повторы ID либо найдены недемо-уроки.
    """
    subjects = [Subject(id=row.id, name=row.name) for row in data.subjects]
    if len({row.id for row in subjects}) != len(subjects):
        raise ValueError("Duplicate subject IDs")
    engine = create_engine(Settings().database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            other = await session.scalar(
                select(ScheduledLessonRow.id)
                .where(
                    ScheduledLessonRow.subject_id.in_([row.id for row in subjects]),
                    ScheduledLessonRow.teacher_id.not_in(data.allowed_teacher_ids),
                )
                .limit(1)
            )
            if other is not None:
                raise ValueError(
                    "Non-demo lessons use these subject IDs; names were not changed"
                )
            # Справочник и проверка используют ту же транзакцию/сессию.
            from schedule_service.infrastructure.subject_repository import (
                SqlAlchemySubjectRepository,
            )

            repository = SqlAlchemySubjectRepository(session)
            for subject in subjects:
                await repository.set_name(subject)
    finally:
        await engine.dispose()


def main() -> None:
    """Запускает локальное заполнение без вывода конфигурации или секретов."""
    data = SubjectNamesInput.model_validate_json(sys.stdin.buffer.read(262145))
    asyncio.run(set_subject_names(data))
    print("Subject names checked and saved")


if __name__ == "__main__":
    main()
