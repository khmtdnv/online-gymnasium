"""Безопасные ответы закрытого API без деталей библиотек и секретов."""

from fastapi import HTTPException


class HomeworkHTTPError(HTTPException):
    """Передаёт HTTP-статус и стабильный код ошибки для Gateway."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        """Сохраняет безопасное сообщение и код машинного контракта.

        Args:
            status_code: Статус отказа.
            code: Код, распознаваемый Gateway.
            message: Описание без технических подробностей.
        """
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def unavailable() -> HomeworkHTTPError:
    """Возвращает отказ без обещания, что предыдущая запись была отменена."""
    return HomeworkHTTPError(503, "service_unavailable", "Service unavailable")
