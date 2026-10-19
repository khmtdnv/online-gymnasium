from typing import Protocol


class PasswordService(Protocol):
    """Контракт создания хеша пароля и проверки открытого пароля."""

    def hash(self, plain_password: str) -> str:
        """Вычисляет хеш открытого пароля для хранения.

        Args:
            plain_password: Открытый пароль для вычисления или проверки хеша.

        Returns:
            Строка хеша с солью и параметрами алгоритма.
        """
        ...

    def verify(self, plain_password: str, password_hash: str) -> bool:
        """Сравнивает открытый пароль с сохранённым хешем.

        Args:
            plain_password: Открытый пароль для вычисления или проверки хеша.
            password_hash: Сохранённая строка хеша пароля.

        Returns:
            True, если пароль соответствует хешу; иначе False.
        """
        ...
