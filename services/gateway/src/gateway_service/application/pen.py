"""Независимый wire-контракт Pen, без импорта кода соседнего сервиса."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PenPoint(BaseModel):
    """Нормализованная координата, одинаковая на любом размере холста."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class PenBatch(BaseModel):
    """Идентичный повтор обязан сохранить все поля, включая UUID пачки."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    batch_id: UUID
    sequence: int = Field(strict=True, ge=1, le=4096)
    stroke_id: UUID
    points: list[PenPoint] = Field(min_length=1, max_length=64)
    finished: bool = Field(strict=True)


class SavedPenBatch(PenBatch):
    """Данные, commit которых уже подтвердил Pen."""

    id: int = Field(strict=True, ge=1)


class PenAuthentication(BaseModel):
    """Первое сообщение WebSocket, токен никогда не входит в URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    access_token: str = Field(strict=True, min_length=1, max_length=4096)
    after: int = Field(default=0, strict=True, ge=0, le=4096)
