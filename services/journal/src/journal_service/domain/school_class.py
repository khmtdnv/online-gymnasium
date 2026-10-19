"""Данные школьного класса и правила их корректности."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Class:
    """Школьный класс; до сохранения ID и время создания отсутствуют."""

    name: str
    study_year: int
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Очищает имя и проверяет его длину и диапазон учебного года.

        Raises:
            ValueError: Имя пустое, длиннее 64 символов, содержит NUL
                или год вне диапазона.
        """
        normalized_name = self.name.strip()

        self.name = normalized_name

        if "\x00" in self.name:
            raise ValueError("School class name must not contain NUL")

        if len(self.name) < 1:
            raise ValueError("School class name must not be empty")

        if len(self.name) > 64:
            raise ValueError("School class name must not contain more than 64 symbols")

        if self.study_year not in range(1900, 9999):
            raise ValueError(
                "School class study_year must be in range from 1900 to 9998"
            )
