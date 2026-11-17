"""Название учебного предмета без предположений о старых числовых ID."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Subject:
    """Предмет; None означает, что название старой записи ещё не уточнено."""

    id: int
    name: str | None

    def __post_init__(self) -> None:
        """Проверяет ID и запрещает пустое или неаккуратно заполненное название."""
        if type(self.id) is not int or not 1 <= self.id <= 2147483647:
            raise ValueError("Invalid subject ID")
        if self.name is not None and (
            not isinstance(self.name, str)
            or not 1 <= len(self.name) <= 100
            or self.name != self.name.strip()
        ):
            raise ValueError("Invalid subject name")
