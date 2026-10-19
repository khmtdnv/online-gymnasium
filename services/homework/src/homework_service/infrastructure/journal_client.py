"""HTTP-проверка одной пары назначения у Journal."""

from typing import Self
from uuid import UUID

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from homework_service.application.ports.errors import OwnerLookupUnavailableError


class TeacherAssignmentResponse(BaseModel):
    """Минимальное подтверждение конкретного назначения."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    teacher_id: UUID
    class_id: int = Field(ge=1, le=2147483647)


class CurrentPeriodResponse(BaseModel):
    """Принимает только полный открытый период конкретного ученика."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    id: int = Field(ge=1, le=2147483647)
    student_id: UUID
    class_id: int = Field(ge=1, le=2147483647)
    joined_at: AwareDatetime
    left_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_open_period(self) -> Self:
        """Не принимает историю вместо текущего класса."""
        if self.left_at is not None:
            raise ValueError("Expected an open period")
        return self


class HttpJournalReader:
    """Не трактует недоступность Journal как подтверждённое отсутствие связи."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Сохраняет клиент с отдельным credential Homework→Journal.

        Args:
            http_client: Клиент с base_url Journal; жизненным циклом владеет caller.
            service_token: Секрет Homework, не Backoffice.

        Raises:
            ValueError: Служебный токен пустой.
        """
        if not service_token:
            raise ValueError("Journal service token is required")
        self._http_client = http_client
        self._service_token = service_token

    async def is_teacher_assigned(self, teacher_id: UUID, class_id: int) -> bool:
        """Читает и проверяет подтверждение одной пары.

        Args:
            teacher_id: UUID преподавателя из доверенного контекста.
            class_id: ID класса из урока Schedule.

        Returns:
            True при200 и совпавшей паре; False только при404.

        Raises:
            OwnerLookupUnavailableError: Сбой сети, статуса или формата ответа.
        """
        try:
            response = await self._http_client.get(
                f"/internal/teachers/{teacher_id}/classes/{class_id}",
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                return False
            if response.status_code != 200:
                raise OwnerLookupUnavailableError("Unexpected Journal status")
            assignment = TeacherAssignmentResponse.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise OwnerLookupUnavailableError("Journal lookup failed") from exc
        if assignment.teacher_id != teacher_id or assignment.class_id != class_id:
            raise OwnerLookupUnavailableError("Journal assignment mismatch")
        return True

    async def get_current_class_id(self, student_id: UUID) -> int | None:
        """Читает и проверяет период, не кешируя решение о доступе.

        Args:
            student_id: UUID ученика из доверенного контекста.

        Returns:
            Текущий class_id или None только при404.

        Raises:
            OwnerLookupUnavailableError: Сбой сети, статуса или контракта.
        """
        try:
            response = await self._http_client.get(
                f"/internal/students/{student_id}/current-class-period",
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise OwnerLookupUnavailableError("Current class lookup failed")
            period = CurrentPeriodResponse.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise OwnerLookupUnavailableError("Invalid current class response") from exc
        if period.student_id != student_id:
            raise OwnerLookupUnavailableError("Student identity mismatch")
        return period.class_id
