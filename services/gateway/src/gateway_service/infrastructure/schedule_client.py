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
