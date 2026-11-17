"""Один запрос выдачи ДЗ с проверкой ответа и без автоматического повтора."""

from datetime import datetime
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkResult,
    HomeworkUnavailableError,
    StudentHomeworkResult,
)
from gateway_service.application.homework_files import HomeworkFileInput
from gateway_service.application.homework_list import (
    HomeworkPageResult,
    ListMyHomeworkQuery,
)
from gateway_service.application.teacher_lessons import TeacherLessonResult
from gateway_service.infrastructure.homework_answers_client import HomeworkAnswersClient

BUSINESS_ERRORS = {
    "access_denied": 403,
    "lesson_not_found": 404,
    "homework_already_exists": 409,
    "invalid_homework_data": 422,
}
student_list_adapter = TypeAdapter(list[StudentHomeworkResult])


class HomeworkClient:
    """Использует отдельный секрет Gateway→Homework, не JWT пользователя."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Сохраняет зависимости; HTTP-клиент закрывается владельцем.

        Args:
            http_client: Клиент с base_url Homework.
            service_token: Отдельный служебный Bearer Gateway.
        """
        self._http_client = http_client
        self._service_token = service_token
        self.answers = HomeworkAnswersClient(http_client, service_token)

    async def _personal_read(
        self, path: str, student_id: UUID, params: dict | None = None
    ) -> httpx.Response:
        """Отправляет только доверенную личность, без автоматических повторов/redirect."""
        try:
            response = await self._http_client.get(
                path,
                params=params,
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "X-Student-ID": str(student_id),
                },
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise HomeworkUnavailableError from exc
        if response.status_code != 200:
            try:
                error = response.json().get("error", {})
                code = error.get("code")
            except (ValueError, AttributeError) as exc:
                raise HomeworkUnavailableError from exc
            if (
                code in ("lesson_not_found", "invalid_homework_data")
                and {"lesson_not_found": 404, "invalid_homework_data": 422}[code]
                == response.status_code
            ):
                raise HomeworkRequestError(response.status_code, code)
            raise HomeworkUnavailableError
        return response

    async def get_student_lesson(
        self, *, student_id: UUID, lesson_id: int
    ) -> TeacherLessonResult:
        """Читает карточку после актуальной проверки класса в Homework."""
        response = await self._personal_read(
            f"/internal/student-lessons/{lesson_id}", student_id
        )
        try:
            result = TeacherLessonResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        if result.lesson.id != lesson_id:
            raise HomeworkUnavailableError
        return result

    async def list_my_homework(self, query: ListMyHomeworkQuery) -> HomeworkPageResult:
        """Проверяет период, фильтр и границы полученной страницы."""
        response = await self._personal_read(
            "/internal/student-homework-view",
            query.student_id,
            query.model_dump(mode="json", exclude={"student_id"}),
        )
        try:
            page = HomeworkPageResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        if (
            page.date_from != query.date_from
            or page.date_to != query.date_to
            or len(page.items) > query.limit
            or len({row.id for row in page.items}) != len(page.items)
            or page.total < len(page.items)
        ):
            raise HomeworkUnavailableError
        for row in page.items:
            if query.state == "needs_action" and row.latest_answer_status not in (
                None,
                "returned",
            ):
                raise HomeworkUnavailableError
            if (
                query.state not in ("all", "needs_action")
                and row.latest_answer_status != query.state
            ):
                raise HomeworkUnavailableError
        return page

    async def get_teacher_lesson(
        self, *, teacher_id: UUID, lesson_id: int
    ) -> TeacherLessonResult:
        """Читает карточку своего урока и проверяет все связи ответа.

        Args:
            teacher_id: UUID из проверенного пользователя Gateway.
            lesson_id: Запрошенный ID урока.

        Returns:
            Проверенная карточка с двумя группами заданий.

        Raises:
            HomeworkRequestError: Подтверждённый запрет403 либо отсутствие404.
            HomeworkUnavailableError: Сбой сети, статуса или контракта.
        """
        try:
            response = await self._http_client.get(
                f"/internal/teacher-lessons/{lesson_id}",
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "X-Teacher-ID": str(teacher_id),
                },
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise HomeworkUnavailableError from exc
        if response.status_code != 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise HomeworkUnavailableError from exc
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            if (
                isinstance(code, str)
                and {"access_denied": 403, "lesson_not_found": 404}.get(code)
                == response.status_code
            ):
                raise HomeworkRequestError(response.status_code, code)
            raise HomeworkUnavailableError
        try:
            result = TeacherLessonResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        if result.lesson.id != lesson_id or result.lesson.teacher_id != teacher_id:
            raise HomeworkUnavailableError
        return result

    async def create_homework(
        self,
        *,
        teacher_id: UUID,
        issued_lesson_id: int,
        description: str,
        due_lesson_id: int | None,
        manual_due_datetime: datetime | None,
        files: list[HomeworkFileInput] | None = None,
    ) -> HomeworkResult:
        """Создаёт задание и проверяет совпадение ответа с отправленным запросом.

        Args:
            teacher_id: UUID из аутентификации, не из пользовательского тела.
            issued_lesson_id: Урок выдачи.
            description: Проверенное описание.
            due_lesson_id: Выбранный урок срока либо None.
            manual_due_datetime: Фиксированная дата либо None.
            files: Описания ожидаемых вложений; байты отправляются отдельно.

        Returns:
            Проверенное сохранённое задание.

        Raises:
            HomeworkRequestError: Подтверждённый бизнес-отказ.
            HomeworkUnavailableError: Сбой сети, статуса или контракта ответа.
                При таймауте запись могла уже завершиться.
        """
        expected_files = TypeAdapter(list[HomeworkFileInput]).validate_python(
            files or []
        )
        try:
            response = await self._http_client.post(
                f"/internal/lessons/{issued_lesson_id}/homework",
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "X-Teacher-ID": str(teacher_id),
                },
                json={
                    "description": description,
                    "due_lesson_id": due_lesson_id,
                    "manual_due_datetime": manual_due_datetime.isoformat()
                    if manual_due_datetime is not None
                    else None,
                    "files": [file.model_dump() for file in expected_files],
                },
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise HomeworkUnavailableError from exc

        if response.status_code != 201:
            try:
                payload = response.json()
            except ValueError as exc:
                raise HomeworkUnavailableError from exc
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            if (
                isinstance(code, str)
                and BUSINESS_ERRORS.get(code) == response.status_code
            ):
                raise HomeworkRequestError(response.status_code, code)
            raise HomeworkUnavailableError

        try:
            result = HomeworkResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        if (
            result.issued_lesson_id != issued_lesson_id
            or result.author_id != teacher_id
            or result.description != description
            or result.due_lesson_id != due_lesson_id
            or result.manual_due_datetime != manual_due_datetime
            or len(result.files) != len(expected_files)
            or any(
                actual.file_name != expected.file_name
                or actual.size_bytes != expected.size_bytes
                or actual.content_type != expected.content_type
                or actual.upload_status != "pending"
                for actual, expected in zip(result.files, expected_files)
            )
        ):
            raise HomeworkUnavailableError
        return result

    async def _get_student_response(
        self,
        path: str,
        student_id: UUID,
        *,
        params: dict[str, int] | None = None,
        allow_not_found: bool = False,
    ) -> httpx.Response:
        """Читает Homework с заново сформированным доверенным контекстом.

        Args:
            path: Закрытый адрес Homework.
            student_id: UUID из аутентификации Gateway.
            params: Только проверенная пагинация.
            allow_not_found: Разрешено ли бизнес-отсутствие отдельного ДЗ.

        Returns:
            Успешный200-ответ для последующей проверки JSON.

        Raises:
            HomeworkRequestError: Подтверждённое отсутствие отдельного задания.
            HomeworkUnavailableError: Все прочие ошибки служебного запроса.
        """
        try:
            response = await self._http_client.get(
                path,
                params=params,
                headers={
                    "Authorization": f"Bearer {self._service_token}",
                    "X-Student-ID": str(student_id),
                },
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise HomeworkUnavailableError from exc
        if response.status_code != 200:
            if allow_not_found and response.status_code == 404:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HomeworkUnavailableError from exc
                error = payload.get("error") if isinstance(payload, dict) else None
                if (
                    isinstance(error, dict)
                    and error.get("code") == "homework_not_found"
                ):
                    raise HomeworkRequestError(404, "homework_not_found")
            raise HomeworkUnavailableError
        return response

    async def list_student_homework(
        self,
        *,
        student_id: UUID,
        limit: int,
        offset: int,
    ) -> list[StudentHomeworkResult]:
        """Читает страницу и проверяет её размер, класс, порядок и уникальность.

        Args:
            student_id: Доверенный UUID ученика.
            limit: Проверенный размер страницы.
            offset: Проверенное смещение.

        Returns:
            Проверенная страница заданий.

        Raises:
            HomeworkUnavailableError: Сбой связи, статуса или контракта страницы.
        """
        response = await self._get_student_response(
            "/internal/homework",
            student_id,
            params={"limit": limit, "offset": offset},
        )
        try:
            result = student_list_adapter.validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        keys = [(row.created_at, row.id) for row in result]
        if (
            len(result) > limit
            or len({row.id for row in result}) != len(result)
            or len({row.class_id for row in result}) > 1
            or keys != sorted(keys, reverse=True)
        ):
            raise HomeworkUnavailableError
        return result

    async def get_student_homework(
        self,
        *,
        student_id: UUID,
        homework_id: int,
    ) -> StudentHomeworkResult:
        """Проверяет ответ отдельного ДЗ, не подменяя авторизацию владельца.

        Args:
            student_id: Доверенный UUID ученика.
            homework_id: Запрошенный ID задания.

        Returns:
            Задание с совпавшим ID и корректным сроком.

        Raises:
            HomeworkRequestError: Доступное задание отсутствует.
            HomeworkUnavailableError: Сбой связи или контракта ответа.
        """
        response = await self._get_student_response(
            f"/internal/homework/{homework_id}",
            student_id,
            allow_not_found=True,
        )
        try:
            result = StudentHomeworkResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        if result.id != homework_id:
            raise HomeworkUnavailableError
        return result
