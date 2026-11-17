"""Ограниченные личные уведомления, без произвольных внешних ссылок."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Notification(BaseModel):
    """Gateway повторно проверяет контракт владельца перед передачей браузеру."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int = Field(strict=True, ge=1, le=2147483647)
    event_id: UUID
    recipient_id: UUID
    title: str = Field(strict=True, min_length=1, max_length=200)
    body: str = Field(strict=True, min_length=1, max_length=500)
    link: str = Field(
        strict=True,
        pattern=r"^/(billing|homework/[1-9][0-9]{0,9}|documents/[0-9a-fA-F-]{36})$",
    )
    created_at: AwareDatetime
    read_at: AwareDatetime | None


class NotificationCount(BaseModel):
    """Отрицательные и строковые счётчики не считаются доверенным ответом."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    unread: int = Field(strict=True, ge=0, le=2147483647)
