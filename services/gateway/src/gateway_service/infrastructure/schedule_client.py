"""Чтение собственного расписания с проверкой служебного ответа."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.teacher_lessons import (
    LessonInfo,
    ScheduleUnavailableError,
)

lesson_list_adapter = TypeAdapter(list[LessonInfo])


class ScheduleClient:
    """Передаёт доверенного преподавателя с отдельным секретом Gateway."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Сохраняет клиент, жизненным циклом которого владеет Gateway.

        Args:
            http_client: HTTP-клиент с base_url Schedule.
            service_token: Секрет пары Gateway→Schedule.
        """
        self._http_client = http_client
        self._service_token = service_token

    async def get_lesson(self, lesson_id: int) -> LessonInfo | None:
        """Возвращает авторитетный урок; None только при подтверждённом404."""
        try:
            response = await self._http_client.get(
                f"/internal/gateway-lessons/{lesson_id}",
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise ScheduleUnavailableError
            lesson = LessonInfo.model_validate_json(response.content)
            if lesson.id != lesson_id:
                raise ScheduleUnavailableError
            return lesson
        except (httpx.HTTPError, ValidationError) as exc:
            raise ScheduleUnavailableError from exc

    async def list_calendar_lessons(
        self,
        *,
        class_id: int | None,
        teacher_id: UUID | None,
        starts_at_from: datetime,
        starts_at_until: datetime,
    ) -> list[LessonInfo]:
        """Читает проверенный интервал с единственным доверенным владельцем."""
        if (class_id is None) == (teacher_id is None):
            raise ScheduleUnavailableError
        params = {
            "starts_at_from": starts_at_from.isoformat(),
            "starts_at_until": starts_at_until.isoformat(),
        }
        params["class_id" if class_id is not None else "teacher_id"] = str(
            class_id if class_id is not None else teacher_id
        )
        try:
            response = await self._http_client.get(
                "/internal/calendar-lessons",
                params=params,
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ScheduleUnavailableError
            rows = lesson_list_adapter.validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise ScheduleUnavailableError from exc
        keys = [(row.starts_at, row.id) for row in rows]
        if (
            len(rows) > 1000
            or len({row.id for row in rows}) != len(rows)
            or keys != sorted(keys)
            or any(
                (class_id is not None and row.class_id != class_id)
                or (teacher_id is not None and row.teacher_id != teacher_id)
                or row.starts_at >= starts_at_until
                or row.ends_at <= starts_at_from
                for row in rows
            )
        ):
            raise ScheduleUnavailableError
        return rows

    async def get_subject_names(self, subject_ids: list[int]) -> dict[int, str | None]:
        """Получает справочник пакетом; отсутствующее имя не выдумывает."""
        from pydantic import BaseModel, ConfigDict, Field

        class SubjectResponse(BaseModel):
            model_config = ConfigDict(frozen=True, extra="forbid")
            id: int = Field(strict=True, ge=1, le=2147483647)
            name: str | None = Field(
                default=None, strict=True, min_length=1, max_length=100
            )

        ids = sorted(set(subject_ids))
        if not ids:
            return {}
        if len(ids) > 1000:
            raise ScheduleUnavailableError
        try:
            response = await self._http_client.post(
                "/internal/subjects/lookup",
                json={"ids": ids},
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ScheduleUnavailableError
            rows = TypeAdapter(list[SubjectResponse]).validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise ScheduleUnavailableError from exc
        if len({row.id for row in rows}) != len(rows) or not {
            row.id for row in rows
        } <= set(ids):
            raise ScheduleUnavailableError
        return {row.id: row.name for row in rows}

    async def list_teacher_lessons(
        self, *, teacher_id: UUID, date_from: date, date_to: date
    ) -> list[LessonInfo]:
        """Проверяет владельца, уникальность, порядок и пересечение диапазона.

        Args:
            teacher_id: UUID из аутентификации Gateway.
            date_from: Первая дата диапазона UTC.
            date_to: Последняя дата включительно.

        Returns:
            Проверенные уроки в исходном порядке.

        Raises:
            ScheduleUnavailableError: Сбой сети, статуса или контракта ответа.
        """
        try:
            response = await self._http_client.get(
                "/internal/teacher-lessons",
                params={
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                },
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "X-Teacher-ID": str(teacher_id),
                },
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise ScheduleUnavailableError
            lessons = lesson_list_adapter.validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise ScheduleUnavailableError from exc
        range_start = datetime.combine(date_from, time.min, UTC)
        range_end = datetime.combine(date_to + timedelta(days=1), time.min, UTC)
        keys = [(lesson.starts_at, lesson.id) for lesson in lessons]
        if (
            len({lesson.id for lesson in lessons}) != len(lessons)
            or keys != sorted(keys)
            or any(
                lesson.teacher_id != teacher_id
                or lesson.starts_at >= range_end
                or lesson.ends_at <= range_start
                for lesson in lessons
            )
        ):
            raise ScheduleUnavailableError
        return lessons
