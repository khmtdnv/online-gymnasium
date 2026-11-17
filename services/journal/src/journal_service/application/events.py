"""Данные интеграционных событий Journal; это не HTTP-ответы и не ORM."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict


class StudentAddedToClassEvent(BaseModel):
    """Описывает добавление ученика, которое нужно сохранить для публикации."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_id: UUID
    occurred_at: AwareDatetime
    request_id: str
    actor_id: str
    student_id: UUID
    period_id: int
    class_id: int


class StudentTransferredToClassEvent(BaseModel):
    """Описывает перевод из исходного периода в новый с общей датой границы."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_id: UUID
    occurred_at: AwareDatetime
    request_id: str
    actor_id: str
    student_id: UUID
    previous_period_id: int
    previous_class_id: int
    period_id: int
    class_id: int


class StudentClassPeriodEndedEvent(BaseModel):
    """Описывает закрытие периода без назначения ученика в новый класс."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_id: UUID
    occurred_at: AwareDatetime
    request_id: str
    actor_id: str
    student_id: UUID
    period_id: int
    class_id: int


type StudentClassChangedEvent = (
    StudentAddedToClassEvent
    | StudentTransferredToClassEvent
    | StudentClassPeriodEndedEvent
)
