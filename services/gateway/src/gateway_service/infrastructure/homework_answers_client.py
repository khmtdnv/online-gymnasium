"""Запросы попыток через существующий JSON-пул Homework без повторов записи."""

from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from gateway_service.application.homework import (
    HomeworkRequestError,
    HomeworkUnavailableError,
)
from gateway_service.application.homework_answers import (
    HomeworkAnswerInput,
    HomeworkAnswerResult,
    HomeworkAnswerReviewInput,
)

ERRORS = {
    "access_denied": 403,
    "homework_answer_not_found": 404,
    "homework_answer_conflict": 409,
    "homework_file_not_ready": 409,
    "invalid_homework_answer": 422,
}
answers_adapter = TypeAdapter(list[HomeworkAnswerResult])


class HomeworkAnswersClient:
    """Передаёт доверенную личность и проверяет принадлежность результата запросу."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Использует пул, жизненным циклом которого управляет приложение."""
        self._http_client = http_client
        self._service_token = service_token

    async def _request(
        self,
        method: str,
        homework_id: int,
        user_id: UUID,
        role: str,
        *,
        suffix: str = "",
        json: dict | None = None,
        params: dict | None = None,
        key: str | None = None,
    ) -> httpx.Response:
        """Отправляет один запрос; неизвестный исход записи оставляет для явного повтора."""
        headers = {
            "Authorization": f"Bearer {self._service_token}",
            "X-User-ID": str(user_id),
            "X-User-Role": role,
        }
        if key is not None:
            headers["Idempotency-Key"] = key
        try:
            response = await self._http_client.request(
                method,
                f"/internal/homework/{homework_id}/answers{suffix}",
                headers=headers,
                json=json,
                params=params,
                timeout=5.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise HomeworkUnavailableError from exc
        if response.status_code not in ((200, 201) if method == "POST" else (200,)):
            try:
                code = response.json()["error"]["code"]
            except (ValueError, KeyError, TypeError) as exc:
                raise HomeworkUnavailableError from exc
            if isinstance(code, str) and ERRORS.get(code) == response.status_code:
                raise HomeworkRequestError(response.status_code, code)
            raise HomeworkUnavailableError
        return response

    @staticmethod
    def _answer(
        response: httpx.Response, homework_id: int, answer_id: int | None = None
    ) -> HomeworkAnswerResult:
        """Проверяет JSON и совпадение адреса с родительским заданием."""
        try:
            answer = HomeworkAnswerResult.model_validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        if (
            answer.homework_id != homework_id
            or answer_id is not None
            and answer.id != answer_id
        ):
            raise HomeworkUnavailableError
        return answer

    async def submit(
        self, student_id: UUID, homework_id: int, key: str, body: HomeworkAnswerInput
    ) -> tuple[HomeworkAnswerResult, bool]:
        """Возвращает сохранённую попытку и признак нового создания201."""
        response = await self._request(
            "POST",
            homework_id,
            student_id,
            "student",
            json=body.model_dump(mode="json"),
            key=key,
        )
        answer = self._answer(response, homework_id)
        if (
            answer.student_id != student_id
            or answer.answer_text != body.answer_text
            or len(answer.files) != len(body.files)
            or any(
                actual.file_name != expected.file_name
                or actual.size_bytes != expected.size_bytes
                or actual.content_type != expected.content_type
                for actual, expected in zip(answer.files, body.files)
            )
        ):
            raise HomeworkUnavailableError
        return answer, response.status_code == 201

    async def list_answers(
        self,
        user_id: UUID,
        role: str,
        homework_id: int,
        *,
        student_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[HomeworkAnswerResult]:
        """Читает ограниченную страницу, не позволяя источнику подменить ученика."""
        params = {"limit": limit, "offset": offset}
        if student_id is not None:
            params["student_id"] = str(student_id)
        response = await self._request("GET", homework_id, user_id, role, params=params)
        try:
            answers = answers_adapter.validate_json(response.content)
        except ValidationError as exc:
            raise HomeworkUnavailableError from exc
        expected_student = user_id if role == "student" else student_id
        if (
            len(answers) > limit
            or len({answer.id for answer in answers}) != len(answers)
            or any(
                answer.homework_id != homework_id
                or expected_student is not None
                and answer.student_id != expected_student
                for answer in answers
            )
        ):
            raise HomeworkUnavailableError
        return answers

    async def get_answer(
        self, user_id: UUID, role: str, homework_id: int, answer_id: int
    ) -> HomeworkAnswerResult:
        """Читает один разрешённый ответ по точному адресу."""
        answer = self._answer(
            await self._request(
                "GET", homework_id, user_id, role, suffix=f"/{answer_id}"
            ),
            homework_id,
            answer_id,
        )
        if role == "student" and answer.student_id != user_id:
            raise HomeworkUnavailableError
        return answer

    async def review(
        self,
        teacher_id: UUID,
        homework_id: int,
        answer_id: int,
        body: HomeworkAnswerReviewInput,
    ) -> HomeworkAnswerResult:
        """Проверяет совпадение сохранённого решения с отправленным."""
        answer = self._answer(
            await self._request(
                "PUT",
                homework_id,
                teacher_id,
                "teacher",
                suffix=f"/{answer_id}/review",
                json=body.model_dump(mode="json"),
            ),
            homework_id,
            answer_id,
        )
        if (
            answer.status != body.status
            or answer.grade != body.grade
            or answer.teacher_comment != body.teacher_comment
            or answer.reviewer_id != teacher_id
        ):
            raise HomeworkUnavailableError
        return answer
