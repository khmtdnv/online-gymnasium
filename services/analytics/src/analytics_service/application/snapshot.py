from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def _aware_datetime(value: object, name: str) -> datetime:
    """Разбирает ISO-время события с обязательным известным смещением UTC.

    Args:
        value: Строка из внешнего события.
        name: Название поля для диагностики.

    Returns:
        Момент времени с часовым поясом.

    Raises:
        ValueError: Строка неверна или смещение отсутствует.
        TypeError: Поле не является строкой.
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO datetime string")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError(f"{name} must have a known UTC offset")
    return result


class LessonSnapshot(BaseModel):
    """Состояние урока вместе с ID и временем полученного события."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_id: int = Field(gt=0)
    occurred_at: AwareDatetime
    lesson_id: int = Field(gt=0)
    class_id: int = Field(gt=0)
    teacher_id: UUID
    subject_id: int = Field(gt=0)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: Literal["planned", "canceled"]
    version: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Сравнивает начало и конец как моменты времени в UTC.

        Returns:
            Снимок с допустимым интервалом.

        Raises:
            ValueError: Начало не предшествует окончанию.
        """
        if self.starts_at.astimezone(UTC) >= self.ends_at.astimezone(UTC):
            raise ValueError("starts_at must precede ends_at")
        return self


def parse_lesson_snapshot(envelope: dict[str, object]) -> LessonSnapshot | None:
    """Преобразует конверт события lesson.snapshot в снимок урока.

    Args:
        envelope: Разобранный конверт события с метаданными и payload.

    Returns:
        Снимок урока; None для другого типа события.

    Raises:
        ValueError: Отсутствует обязательное поле, дата не имеет смещения
            или снимок нарушает контракт идентификаторов, статуса и интервала.
        TypeError: Payload или переданное значение имеет неподходящий тип.
    """
    if not isinstance(envelope, dict):
        raise TypeError("envelope must be an object")
    event_type = envelope.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("event_type must be a nonempty string")
    if event_type != "lesson.snapshot":
        return None
    if (
        type(envelope.get("schema_version")) is not int
        or envelope["schema_version"] != 2
    ):
        raise ValueError("Unsupported lesson.snapshot schema_version")

    payload = envelope.get("payload")

    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")

    try:
        teacher_id = payload["teacher_id"]
        if not isinstance(teacher_id, str):
            raise TypeError("teacher_id must be a UUID string")
        starts_at = _aware_datetime(payload["starts_at"], "starts_at")
        ends_at = _aware_datetime(payload["ends_at"], "ends_at")
        return LessonSnapshot(
            event_id=envelope["event_id"],
            occurred_at=_aware_datetime(envelope["occurred_at"], "occurred_at"),
            lesson_id=payload["lesson_id"],
            class_id=payload["class_id"],
            teacher_id=UUID(teacher_id),
            subject_id=payload["subject_id"],
            starts_at=starts_at,
            ends_at=ends_at,
            status=payload["status"],
            version=payload["version"],
        )
    except KeyError as exc:
        raise ValueError(f"Missing required field: {exc.args[0]}") from exc
