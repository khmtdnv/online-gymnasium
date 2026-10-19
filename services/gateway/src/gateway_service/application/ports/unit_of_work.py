from types import TracebackType
from typing import Protocol, Self

from gateway_service.application.ports.user_repository import UserRepository


class UnitOfWork(Protocol):
    """Граница транзакции и доступа к репозиториям одного сценария."""

    users: UserRepository

    async def __aenter__(self) -> Self:
        """Открывает сессию и предоставляет репозитории одной транзакции.

        Returns:
            Этот объект с репозиториями текущей сессии.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Завершает транзакцию и закрывает сессию.

        При успешном выходе выполняет commit, при исключении выполняет rollback.

        Args:
            exc_type: Тип исключения при выходе; None при успешном завершении.
            exc: Исключение, которое нужно обработать, если оно возникло.
            tb: Объект traceback исключения, если оно возникло.
        """
        ...
