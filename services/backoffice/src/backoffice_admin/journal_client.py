"""Служебный HTTP-клиент Journal без доступа к его базе данных."""

from itertools import pairwise
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


class JournalClass(BaseModel):
    """Проверенный класс для выбора по названию и учебному году."""

    model_config = ConfigDict(frozen=True)
    id: int = Field(strict=True, ge=1)
    name: str
    study_year: int = Field(strict=True, ge=1900, le=9998)
    created_at: AwareDatetime


class JournalClassPeriod(BaseModel):
    """Проверенный открытый период из успешного ответа Journal."""

    model_config = ConfigDict(frozen=True)
    id: int = Field(strict=True, ge=1)
    student_id: UUID
    class_id: int = Field(strict=True, ge=1)
    joined_at: AwareDatetime
    left_at: None


class AddStudentToClassResult(BaseModel):
    """Период и признак создания, полученный из HTTP-статуса Journal."""

    model_config = ConfigDict(frozen=True, strict=True)
    period: JournalClassPeriod
    created: bool


class JournalProtocolError(Exception):
    """Journal вернул статус или данные, не соответствующие контракту."""


classes_adapter = TypeAdapter(list[JournalClass])


class JournalBackofficeClient:
    """Читает классы и отправляет административные команды в Journal."""

    def __init__(self, http_client: httpx.Client, service_token: str) -> None:
        """Сохраняет переданный клиент и отдельный служебный секрет Journal.

        Args:
            http_client: Клиент с base_url, timeout и запретом перенаправлений.
            service_token: Входящий секрет Backoffice, настроенный в Journal.
        """
        self._client = http_client
        self._service_token = service_token

    def assign_teacher_to_class(
        self, teacher_id: UUID, class_id: int, actor_id: str
    ) -> bool:
        """Назначает преподавателя, различая создание и безопасный повтор.

        Args:
            teacher_id: Проверенный UUID преподавателя.
            class_id: Выбранный ID класса.
            actor_id: ID сотрудника из Django-сессии.

        Returns:
            True при201; False при204.

        Raises:
            JournalProtocolError: Неожиданный успешный ответ.
            httpx.HTTPError: Ошибка статуса или связи; результат может быть неизвестен.
        """
        response = self._client.put(
            f"/internal/teachers/{teacher_id}/classes/{class_id}",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-Actor-ID": actor_id,
            },
        )
        response.raise_for_status()
        if response.status_code not in (201, 204) or response.content:
            raise JournalProtocolError("Invalid teacher assignment response")
        return response.status_code == 201

    def unassign_teacher_from_class(
        self, teacher_id: UUID, class_id: int, actor_id: str
    ) -> None:
        """Снимает назначение, не запрашивая профиль преподавателя.

        Args:
            teacher_id: UUID из проверенной формы.
            class_id: ID удаляемой связи.
            actor_id: ID сотрудника из Django-сессии.

        Raises:
            JournalProtocolError: Ответ не пустой204.
            httpx.HTTPError: Ошибка статуса или связи.
        """
        response = self._client.delete(
            f"/internal/teachers/{teacher_id}/classes/{class_id}",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-Actor-ID": actor_id,
            },
        )
        response.raise_for_status()
        if response.status_code != 204 or response.content:
            raise JournalProtocolError("Invalid teacher removal response")

    def list_classes_for_teacher(self, teacher_id: UUID) -> list[JournalClass]:
        """Читает все страницы назначений с проверкой порядка и повторов.

        Args:
            teacher_id: UUID выбранного преподавателя.

        Returns:
            Классы по возрастанию ID; пустой список допустим.

        Raises:
            JournalProtocolError: Статус/JSON/размер/порядок страницы нарушен.
            httpx.HTTPError: Ошибка статуса или связи.
        """
        classes = []
        while True:
            response = self._client.get(
                f"/internal/teachers/{teacher_id}/classes",
                params={"limit": 100, "offset": len(classes)},
                headers={"Authorization": f"Bearer {self._service_token}"},
            )
            response.raise_for_status()
            if response.status_code != 200:
                raise JournalProtocolError("Invalid teacher classes status")
            try:
                page = classes_adapter.validate_json(response.content)
            except ValidationError as exc:
                raise JournalProtocolError("Invalid teacher classes response") from exc
            if len(page) > 100:
                raise JournalProtocolError("Teacher classes page too large")
            combined = classes + page
            if any(a.id >= b.id for a, b in pairwise(combined)):
                raise JournalProtocolError("Unordered or repeated teacher classes")
            classes.extend(page)
            if len(page) < 100:
                return classes

    def list_classes(self) -> list[JournalClass]:
        """Загружает все страницы классов для выпадающего списка.

        Returns:
            Классы в порядке Journal; пустой список, если классов нет.

        Raises:
            JournalProtocolError: Неверный ответ или повторяющаяся страница.
            httpx.HTTPStatusError: Journal отклонил запрос.
            httpx.RequestError: Ответ не удалось получить.
        """
        classes = []
        seen_ids = set()

        while True:
            response = self._client.get(
                "/internal/classes",
                params={"limit": 100, "offset": len(classes)},
                headers={"Authorization": f"Bearer {self._service_token}"},
            )
            response.raise_for_status()

            if response.status_code != 200:
                raise JournalProtocolError("Unexpected classes status")

            try:
                page = classes_adapter.validate_json(response.content)
            except ValidationError as exc:
                raise JournalProtocolError("Invalid classes response") from exc

            if len(page) > 100:
                raise JournalProtocolError("Classes page exceeds requested size")

            for school_class in page:
                if school_class.id in seen_ids:
                    raise JournalProtocolError("Duplicate class in paginated response")
                seen_ids.add(school_class.id)
                classes.append(school_class)

            if len(page) < 100:
                return classes

    def add_student_to_class(
        self, student_id: UUID, class_id: int, actor_id: str
    ) -> AddStudentToClassResult:
        """Отправляет назначение и проверяет результат Journal.

        Args:
            student_id: UUID ученика из проверенной формы.
            class_id: ID класса из проверенного списка выбора.
            actor_id: ID сотрудника из request.user.pk, не из формы.

        Returns:
            Проверенный период и created=True для 201 или False для 200.

        Raises:
            JournalProtocolError: Неожиданный успешный статус, неверный JSON
                либо ответ относится к другому ученику или классу.
            httpx.HTTPStatusError: Journal вернул ошибку или перенаправление.
            httpx.RequestError: Результат запроса неизвестен из-за сбоя связи.
        """
        response = self._client.put(
            f"/internal/students/{student_id}/current-class-period",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-Actor-ID": actor_id,
            },
            json={"class_id": class_id},
        )
        response.raise_for_status()

        if response.status_code not in (200, 201):
            raise JournalProtocolError

        try:
            period = JournalClassPeriod.model_validate_json(response.content)

            if period.student_id != student_id:
                raise JournalProtocolError

            if period.class_id != class_id:
                raise JournalProtocolError

            return AddStudentToClassResult(
                period=period, created=response.status_code == 201
            )
        except ValidationError as exc:
            raise JournalProtocolError("Invalid class period response") from exc

    def get_current_period_for_student(
        self, student_id: UUID
    ) -> JournalClassPeriod | None:
        """Читает текущий период, не считая404 отсутствием пользователя Gateway.

        Args:
            student_id: Проверенный UUID ученика.

        Returns:
            Открытый период либо None, если он отсутствует.

        Raises:
            JournalProtocolError: Неверный контракт или чужой период.
            httpx.HTTPError: Сбой связи или ошибочный HTTP-статус.
        """
        response = self._client.get(
            f"/internal/students/{student_id}/current-class-period",
            headers={"Authorization": f"Bearer {self._service_token}"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._read_open_period(response, student_id)

    def transfer_student_to_class(
        self,
        student_id: UUID,
        target_class_id: int,
        expected_period_id: int,
        actor_id: str,
    ) -> JournalClassPeriod:
        """Переводит только из ожидаемого периода, не повторяя команду автоматически.

        Args:
            student_id: Ученик из выбранного профиля.
            target_class_id: Целевой класс из проверенной формы.
            expected_period_id: Исходный период, показанный сотруднику.
            actor_id: Сотрудник из серверного request.user.pk.

        Returns:
            Проверенный открытый период в целевом классе.

        Raises:
            JournalProtocolError: Ответ не соответствует ученику/классу или схеме.
            httpx.HTTPError: Ошибка статуса или неизвестный результат из-за сети.
        """
        response = self._client.post(
            f"/internal/students/{student_id}/current-class-period/transfer",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-Actor-ID": actor_id,
            },
            json={
                "target_class_id": target_class_id,
                "expected_period_id": expected_period_id,
            },
        )
        response.raise_for_status()
        period = self._read_open_period(response, student_id)
        if period.class_id != target_class_id:
            raise JournalProtocolError("Unexpected target class")
        return period

    def end_student_class_period(
        self, student_id: UUID, expected_period_id: int, actor_id: str
    ) -> None:
        """Завершает ожидаемый период и требует пустой204 без попытки прочитать JSON.

        Args:
            student_id: UUID ученика из выбранного профиля.
            expected_period_id: Исходный период формы.
            actor_id: Сотрудник из серверного request.user.pk.

        Raises:
            JournalProtocolError: Статус отличается от204 или ответ содержит тело.
            httpx.HTTPError: Ошибочный статус либо неизвестный результат запроса.
        """
        response = self._client.delete(
            f"/internal/students/{student_id}/current-class-period",
            params={"expected_period_id": expected_period_id},
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "X-Actor-ID": actor_id,
            },
        )
        response.raise_for_status()
        if response.status_code != 204 or response.content:
            raise JournalProtocolError("Expected empty 204 response")

    @staticmethod
    def _read_open_period(
        response: httpx.Response, student_id: UUID
    ) -> JournalClassPeriod:
        """Проверяет успешный ответ о текущем периоде внешнего сервиса.

        Args:
            response: Ответ после проверки ошибочных HTTP-статусов.
            student_id: UUID, для которого выполнялся запрос.

        Returns:
            Проверенный открытый период запрошенного ученика.

        Raises:
            JournalProtocolError: Неверный статус, JSON, поля или UUID ученика.
        """
        if response.status_code != 200:
            raise JournalProtocolError("Unexpected class period status")
        try:
            period = JournalClassPeriod.model_validate_json(response.content)
        except ValidationError as exc:
            raise JournalProtocolError("Invalid class period response") from exc
        if period.student_id != student_id:
            raise JournalProtocolError("Unexpected student in class period")
        return period
