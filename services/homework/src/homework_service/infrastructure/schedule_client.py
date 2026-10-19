"""HTTP-чтения Schedule с явной проверкой внешнего контракта."""

import httpx
from pydantic import TypeAdapter, ValidationError

from homework_service.application.ports.errors import OwnerLookupUnavailableError
from homework_service.application.ports.schedule_reader import LessonInfo

next_lesson_adapter = TypeAdapter(LessonInfo | None)
lesson_list_adapter = TypeAdapter(list[LessonInfo])


class HttpScheduleReader:
    """Использует отдельные credentials Homework→Schedule."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Сохраняет клиент, не открывая запрос или собственный жизненный цикл.

        Args:
            http_client: Клиент с base_url Schedule, закрываемый владельцем.
            service_token: Отдельный входящий секрет Homework в Schedule.

        Raises:
            ValueError: Служебный токен пустой.
        """
        if not service_token:
            raise ValueError("Schedule service token is required")
        self._http_client = http_client
        self._service_token = service_token

    async def _get(self, path: str) -> httpx.Response:
        """Выполняет ограниченный по времени запрос без перехода по redirect.

        Args:
            path: Внутренний относительный адрес Schedule.

        Returns:
            Ответ владельца без автоматического преобразования статусов.

        Raises:
            OwnerLookupUnavailableError: Сетевая ошибка или таймаут.
        """
        try:
            return await self._http_client.get(
                path,
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise OwnerLookupUnavailableError("Schedule request failed") from exc

    async def get_lesson(self, lesson_id: int) -> LessonInfo | None:
        """Проверяет статус, JSON и совпадение ID запрошенного урока.

        Args:
            lesson_id: ID исходного или выбранного урока.

        Returns:
            Проверенный урок либо None при404.

        Raises:
            OwnerLookupUnavailableError: Сбой запроса, статуса или контракта.
        """
        response = await self._get(f"/internal/lessons/{lesson_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise OwnerLookupUnavailableError("Unexpected Schedule status")
        try:
            lesson = LessonInfo.model_validate_json(response.content)
        except ValidationError as exc:
            raise OwnerLookupUnavailableError("Invalid Schedule response") from exc
        if lesson.id != lesson_id:
            raise OwnerLookupUnavailableError("Schedule lesson ID mismatch")
        return lesson

    async def get_lessons(self, lesson_ids: list[int]) -> dict[int, LessonInfo]:
        """Получает все выбранные сроки одним пакетом без частичного успеха.

        Args:
            lesson_ids: Уникальные ID уроков, максимум сто.

        Returns:
            Проверенные уроки по ID; пустой словарь без запроса для пустого пакета.

        Raises:
            OwnerLookupUnavailableError: Сбой сети/JSON либо неполный пакет.
        """
        if not lesson_ids:
            return {}
        try:
            response = await self._http_client.post(
                "/internal/lessons/lookup",
                json={"lesson_ids": lesson_ids},
                headers={"Authorization": f"Bearer {self._service_token}"},
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise OwnerLookupUnavailableError("Lesson batch unavailable")
            lessons = lesson_list_adapter.validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise OwnerLookupUnavailableError("Invalid lesson batch") from exc
        by_id = {lesson.id: lesson for lesson in lessons}
        if len(by_id) != len(lessons) or set(by_id) != set(lesson_ids):
            raise OwnerLookupUnavailableError("Lesson batch identity mismatch")
        return by_id

    async def get_next_lesson(self, lesson_id: int) -> LessonInfo | None:
        """Проверяет предложение относительно актуального исходного урока.

        Args:
            lesson_id: ID исходного урока.

        Returns:
            Следующий урок либо None только при200null.

        Raises:
            OwnerLookupUnavailableError: Исходный урок исчез или ответ некорректен.
        """
        source = await self.get_lesson(lesson_id)
        if source is None:
            raise OwnerLookupUnavailableError("Source lesson unavailable")
        response = await self._get(f"/internal/lessons/{lesson_id}/next")
        if response.status_code != 200:
            raise OwnerLookupUnavailableError("Next lesson lookup failed")
        try:
            lesson = next_lesson_adapter.validate_json(response.content)
        except ValidationError as exc:
            raise OwnerLookupUnavailableError("Invalid next lesson response") from exc
        if lesson is not None and (
            lesson.id == source.id
            or lesson.class_id != source.class_id
            or lesson.subject_id != source.subject_id
            or lesson.starts_at <= source.starts_at
            or lesson.status != "planned"
        ):
            raise OwnerLookupUnavailableError("Next lesson does not match source")
        return lesson
