"""Пачки нормализованных координат; размер холста не влияет на сохранение."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Point(BaseModel):
    """Одна координата в пределах0..1, без NaN и бесконечности."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class StrokeBatch(BaseModel):
    """Повтор запроса сохраняет batch_id, sequence и всё содержимое."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    batch_id: UUID
    sequence: int = Field(strict=True, ge=1, le=4096)
    stroke_id: UUID
    points: list[Point] = Field(min_length=1, max_length=64)
    finished: bool = Field(strict=True)


class SavedBatch(StrokeBatch):
    """Подтверждённая запись, уже зафиксированная в PostgreSQL."""

    id: int = Field(strict=True, ge=1)


PositiveId = Annotated[int, Field(ge=1, le=2147483647)]
