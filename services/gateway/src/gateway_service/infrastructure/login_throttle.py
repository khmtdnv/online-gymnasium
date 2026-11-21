"""Ограничение частоты неудачных попыток входа по email."""

import time
from dataclasses import dataclass, field


@dataclass
class LoginThrottle:
    """Блокирует email после серии неудачных входов в пределах окна.

    Хранит отметки времени неудачных попыток в памяти процесса: для одного
    экземпляра сервиса этого достаточно, а успешный вход сбрасывает счётчик,
    чтобы честный пользователь не пострадал от чужих промахов.
    """

    max_failures: int = 10
    window_seconds: float = 900.0
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def is_blocked(self, email: str) -> bool:
        """Сообщает, превышен ли лимит неудачных попыток для email."""
        now = time.monotonic()
        self._forget_expired(email, now)
        return len(self._failures.get(email, ())) >= self.max_failures

    def register_failure(self, email: str) -> None:
        """Добавляет неудачную попытку и забывает истёкшие."""
        now = time.monotonic()
        self._forget_expired(email, now)
        self._failures.setdefault(email, []).append(now)

    def reset(self, email: str) -> None:
        """Сбрасывает счётчик после успешного входа."""
        self._failures.pop(email, None)

    def retry_after_seconds(self, email: str) -> int:
        """Возвращает, сколько секунд ждать до ближайшей возможности входа."""
        now = time.monotonic()
        self._forget_expired(email, now)
        attempts = self._failures.get(email)
        if not attempts:
            return 0
        return max(1, int(self.window_seconds - (now - attempts[0])))

    def _forget_expired(self, email: str, now: float) -> None:
        """Удаляет попытки старше окна."""
        attempts = self._failures.get(email)
        if attempts is None:
            return
        boundary = now - self.window_seconds
        fresh = [stamp for stamp in attempts if stamp > boundary]
        if fresh:
            self._failures[email] = fresh
        else:
            del self._failures[email]
