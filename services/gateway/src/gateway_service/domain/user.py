from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    """Роли продуктовых пользователей онлайн-гимназии."""

    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class User:
    """Данные пользователя для сценариев Gateway, включая хеш пароля."""

    id: UUID
    email: str
    role: Role
    password_hash: str
    is_active: bool
    first_name: str
    last_name: str
    middle_name: str = ""

    def __post_init__(self) -> None:
        """Не допускает пустые имя и фамилию даже при создании вне HTTP.

        Raises:
            ValueError: Часть имени имеет неверный тип, длину или крайние пробелы.
        """
        for name in (self.first_name, self.last_name):
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name) > 100
                or name != name.strip()
            ):
                raise ValueError(
                    "First and last names must contain 1–100 nonblank characters"
                )
        if (
            not isinstance(self.middle_name, str)
            or len(self.middle_name) > 100
            or self.middle_name != self.middle_name.strip()
        ):
            raise ValueError(
                "Middle name must be a trimmed string of at most 100 characters"
            )
