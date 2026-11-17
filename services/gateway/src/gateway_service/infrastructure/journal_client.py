"""Отдельное ограниченное чтение Journal для личных экранов Gateway."""

from uuid import UUID

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)


class JournalUnavailableError(Exception):
    """Journal не подтвердил данные или нарушил контракт ответа."""


class CurrentClassPeriod(BaseModel):
    """Проверенный открытый период именно запрошенного ученика."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(strict=True, ge=1)
    student_id: UUID
    class_id: int = Field(strict=True, ge=1, le=2147483647)
    joined_at: AwareDatetime
    left_at: AwareDatetime | None


class ClassNameResponse(BaseModel):
    """Читаемое название класса без доступа к его изменению."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(strict=True, ge=1, le=2147483647)
    name: str = Field(strict=True, min_length=1, max_length=64)
    study_year: int = Field(strict=True, ge=1900, le=9998)
    created_at: AwareDatetime


class JournalClient:
    """Использует свой read-токен и HTTP-пул, управляемый lifespan Gateway."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        self._http_client = http_client
        self._headers = {"Authorization": f"Bearer {service_token}"}

    async def get_current_class_id(self, student_id: UUID) -> int | None:
        """Возвращает None только при подтверждённом отсутствии текущего периода.

        Args:
            student_id: UUID из авторизации Gateway.

        Returns:
            ID текущего класса либо None.

        Raises:
            JournalUnavailableError: Сеть, статус, закрытый или чужой период.
        """
        try:
            response = await self._http_client.get(
                f"/internal/students/{student_id}/current-class-period",
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise JournalUnavailableError
            period = CurrentClassPeriod.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
        if period.student_id != student_id or period.left_at is not None:
            raise JournalUnavailableError
        return period.class_id

    async def list_current_student_ids(self, class_id: int) -> list[UUID]:
        """Читает текущий состав страницами, не скрывая превышение1000учеников."""
        ids = []
        try:
            for offset in range(0, 1100, 100):
                response = await self._http_client.get(
                    f"/internal/classes/{class_id}/current-periods",
                    params={"limit": 100, "offset": offset},
                    headers=self._headers,
                    timeout=5.0,
                    follow_redirects=False,
                )
                if response.status_code != 200:
                    raise JournalUnavailableError
                rows = TypeAdapter(list[CurrentClassPeriod]).validate_json(
                    response.content
                )
                if len(rows) > 100 or any(
                    row.class_id != class_id or row.left_at is not None for row in rows
                ):
                    raise JournalUnavailableError
                ids.extend(row.student_id for row in rows)
                if len(set(ids)) != len(ids):
                    raise JournalUnavailableError
                if len(ids) > 1000:
                    raise JournalUnavailableError
                if len(rows) < 100:
                    return ids
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
        raise JournalUnavailableError

    async def get_class_names(self, class_ids: list[int]) -> dict[int, str]:
        """Проверяет полноту названий одним запросом, а не на каждую карточку."""
        ids = sorted(set(class_ids))
        if not ids:
            return {}
        if len(ids) > 1000:
            raise JournalUnavailableError
        try:
            response = await self._http_client.post(
                "/internal/classes/lookup",
                json={"ids": ids},
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            rows = TypeAdapter(list[ClassNameResponse]).validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
        if len(rows) != len(ids) or {row.id for row in rows} != set(ids):
            raise JournalUnavailableError
        return {row.id: row.name for row in rows}

    async def list_classes(self, *, limit: int, offset: int) -> list[ClassNameResponse]:
        """Читает страницу выбора класса теми же ограниченными read-правами."""
        try:
            response = await self._http_client.get(
                "/internal/classes",
                params={"limit": limit, "offset": offset},
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            rows = TypeAdapter(list[ClassNameResponse]).validate_json(response.content)
            if len(rows) > limit or len({row.id for row in rows}) != len(rows):
                raise JournalUnavailableError
            return rows
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
