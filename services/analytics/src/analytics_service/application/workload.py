from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict


class ClassDailyWorkload(BaseModel):
    """Готовая дневная нагрузка класса и время обновления расчёта."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    class_id: int
    day: date
    planned_lessons_count: int
    planned_minutes: int
    refreshed_at: AwareDatetime
