from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


@dataclass()
class StudentClassPeriod:
    """Период принадлежности ученика классу; серверные поля появляются в БД."""

    student_id: UUID
    class_id: int
    id: int | None = None
    joined_at: datetime | None = None
    left_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """Вычисляет, остаётся ли период членства открытым.

        Returns:
            True, если время выхода ещё не задано.
        """
        return self.left_at is None

    def __post_init__(self) -> None:
        """Проверяет ID класса, смещения времени и порядок границ периода.

        Raises:
            ValueError: ID неположительный, время без смещения, выход без
                вступления или раньше него.
        """
        if self.class_id <= 0:
            raise ValueError("Class ID must be positive")

        if self.left_at is not None and self.joined_at is None:
            raise ValueError("Joined at must be provided when left at is set")

        if self.left_at is not None and self.left_at.utcoffset() is None:
            raise ValueError("Left at must have a known UTC offset")

        if self.joined_at is not None and self.joined_at.utcoffset() is None:
            raise ValueError("Joined at must have a known UTC offset")

        if (
            self.left_at is not None
            and self.joined_at is not None
            and self.left_at.astimezone(UTC) < self.joined_at.astimezone(UTC)
        ):
            raise ValueError("Left at must not precede joined at")
