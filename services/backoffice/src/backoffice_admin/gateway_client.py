from typing import Literal
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    ValidationError,
)


class GatewayUser(BaseModel):
    """Проверенный ответ Gateway о пользователе без хеша пароля."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    role: Literal["student", "teacher", "parent", "admin"]
    is_active: StrictBool
    first_name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    last_name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    middle_name: str = Field(default="", max_length=100)

    @property
    def display_name(self) -> str:
        """Показывает ФИО и email, чтобы различать однофамильцев."""
        name = " ".join(
            part for part in (self.last_name, self.first_name, self.middle_name) if part
        )
        return f"{name} · {self.email}"


gateway_users_adapter = TypeAdapter(list[GatewayUser])


class GatewayUserAlreadyExistsError(Exception):
    """Gateway отклонил создание пользователя из-за занятого email."""


class GatewayProtocolError(Exception):
    """Gateway вернул ответ, не соответствующий ожидаемому контракту."""


class GatewayBackofficeClient:
    """Вызывает закрытые ручки Gateway и проверяет данные ответов."""

    def __init__(self, http_client: httpx.Client, service_token: str) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            http_client: HTTP-клиент с base_url Gateway и настроенным timeout.
            service_token: Служебный токен для закрытых ручек Gateway.
        """
        self._client = http_client
        self._service_token = service_token

    def create_user(
        self,
        email: str,
        password: str,
        role: str,
        *,
        first_name: str,
        last_name: str,
        middle_name: str = "",
    ) -> GatewayUser:
        """Создаёт пользователя через Gateway и проверяет JSON-ответ.

        Args:
            email: Email пользователя.
            password: Открытый пароль; не сохраняется в базе в таком виде.
            role: Роль пользователя.
            first_name: Обязательное непустое имя.
            last_name: Фамилия; не обязана быть уникальной.
            middle_name: Отчество, если оно есть.

        Returns:
            Проверенные данные нового пользователя.

        Raises:
            GatewayUserAlreadyExistsError: Gateway вернул 409 из-за занятого email.
            GatewayProtocolError: Тело ответа не соответствует модели пользователя.
            httpx.HTTPStatusError: Gateway вернул другой ошибочный HTTP-статус.
            httpx.RequestError: HTTP-запрос не удалось выполнить.
        """
        names = {
            key: value
            for key, value in {
                "first_name": first_name,
                "last_name": last_name,
                "middle_name": middle_name,
            }.items()
            if value
        }
        response = self._client.post(
            "/internal/backoffice/users",
            json={"email": email, "password": password, "role": role, **names},
            headers={"X-Backoffice-Service-Token": self._service_token},
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise GatewayUserAlreadyExistsError from exc
            raise

        try:
            return GatewayUser.model_validate_json(response.content)
        except ValidationError as exc:
            raise GatewayProtocolError("Invalid Gateway user response") from exc

    def list_users(self) -> list[GatewayUser]:
        """Получает список пользователей Gateway и проверяет каждый элемент.

        Returns:
            Список проверенных пользователей.

        Raises:
            GatewayProtocolError: JSON не соответствует списку пользователей.
            httpx.HTTPStatusError: Gateway вернул ошибочный HTTP-статус.
            httpx.RequestError: HTTP-запрос не удалось выполнить.
        """
        response = self._client.get(
            "/internal/backoffice/users",
            headers={"X-Backoffice-Service-Token": self._service_token},
        )

        response.raise_for_status()

        try:
            return gateway_users_adapter.validate_json(response.content)
        except ValidationError as exc:
            raise GatewayProtocolError("Invalid Gateway users response") from exc

    def search_users(
        self,
        query: str,
        *,
        students_only: bool = False,
        role: Literal["teacher"] | None = None,
    ) -> list[GatewayUser]:
        """Получает до 20 совпадений; фильтрацию выполняет Gateway, а не браузер.

        Args:
            query: Проверенные 2–200 символов ФИО или email.
            students_only: Исключить другие роли и неактивных пользователей.
            role: При teacher искать только активных преподавателей.

        Returns:
            Проверенные профили; пустой список, если совпадений нет.

        Raises:
            GatewayProtocolError: Некорректный статус, состав или формат ответа.
            httpx.HTTPError: Ошибочный HTTP-статус либо сбой связи.
        """
        if students_only and role is not None:
            raise ValueError("Conflicting role filters")
        if role not in (None, "teacher"):
            raise ValueError("Unsupported role filter")
        params = {"q": query, "limit": 20}
        if students_only:
            params.update(role="student", active_only="true")
        elif role is not None:
            params.update(role=role, active_only="true")
        response = self._client.get(
            "/internal/backoffice/users/search",
            params=params,
            headers={"X-Backoffice-Service-Token": self._service_token},
        )
        response.raise_for_status()
        try:
            users = gateway_users_adapter.validate_json(response.content)
        except ValidationError as exc:
            raise GatewayProtocolError("Invalid search response") from exc
        if (
            response.status_code != 200
            or len(users) > 20
            or len({user.id for user in users}) != len(users)
        ):
            raise GatewayProtocolError("Invalid search result size or status")
        if students_only and any(
            user.role != "student" or not user.is_active for user in users
        ):
            raise GatewayProtocolError("Unexpected user in student search")
        if role is not None and any(
            user.role != role or not user.is_active for user in users
        ):
            raise GatewayProtocolError("Unexpected user in teacher search")
        return users

    def get_user(self, user_id: UUID) -> GatewayUser:
        """Читает профиль по ID; 404 остаётся HTTPStatusError для страницы.

        Args:
            user_id: UUID пользователя Gateway.

        Returns:
            Профиль без пароля и его хеша.

        Raises:
            GatewayProtocolError: Некорректный ответ или несовпадающий ID.
            httpx.HTTPError: Ошибочный статус либо сбой связи.
        """
        response = self._client.get(
            f"/internal/backoffice/users/{user_id}",
            headers={"X-Backoffice-Service-Token": self._service_token},
        )
        return self._read_profile(response, user_id)

    def update_user_name(
        self, user_id: UUID, *, first_name: str, last_name: str, middle_name: str
    ) -> GatewayUser:
        """Отправляет полное новое ФИО, не меняя пароль, email или роль.

        Args:
            user_id: UUID редактируемого пользователя.
            first_name: Проверенное непустое имя.
            last_name: Проверенная непустая фамилия.
            middle_name: Отчество; пустая строка очищает прежнее значение.

        Returns:
            Подтверждённый профиль с новым ФИО.

        Raises:
            GatewayProtocolError: Ответ не подтверждает запрошенное изменение.
            httpx.HTTPError: Ошибочный статус либо неизвестный результат запроса.
        """
        response = self._client.put(
            f"/internal/backoffice/users/{user_id}/name",
            json={
                "first_name": first_name,
                "last_name": last_name,
                "middle_name": middle_name,
            },
            headers={"X-Backoffice-Service-Token": self._service_token},
        )
        user = self._read_profile(response, user_id)
        if (user.first_name, user.last_name, user.middle_name) != (
            first_name,
            last_name,
            middle_name,
        ):
            raise GatewayProtocolError("Updated names do not match request")
        return user

    @staticmethod
    def _read_profile(response: httpx.Response, user_id: UUID) -> GatewayUser:
        """Проверяет статус, структуру и принадлежность профиля указанному ID."""
        response.raise_for_status()
        try:
            user = GatewayUser.model_validate_json(response.content)
        except ValidationError as exc:
            raise GatewayProtocolError("Invalid profile response") from exc
        if response.status_code != 200 or user.id != user_id:
            raise GatewayProtocolError("Profile response does not match request")
        return user

    def link_parent_student(self, parent_id: UUID, student_id: UUID) -> bool:
        """Создаёт связь родителя и ученика через Gateway.

        Args:
            parent_id: ID пользователя с ролью родителя.
            student_id: ID пользователя с ролью ученика.

        Returns:
            True, если связь создана; False, если она уже существовала.

        Raises:
            GatewayProtocolError: Gateway вернул неожиданный успешный статус.
            httpx.HTTPStatusError: Gateway вернул ошибочный HTTP-статус.
            httpx.RequestError: HTTP-запрос не удалось выполнить.
        """
        response = self._client.put(
            f"/internal/backoffice/parents/{parent_id}/children/{student_id}",
            headers={"X-Backoffice-Service-Token": self._service_token},
        )

        response.raise_for_status()

        if response.status_code == 201:
            return True

        if response.status_code == 204:
            return False

        raise GatewayProtocolError(
            f"Unexpected parent-student link status: {response.status_code}"
        )
