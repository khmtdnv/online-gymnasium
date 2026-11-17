import pwdlib


class PwdlibPasswordService:
    """Создаёт и проверяет хеши паролей средствами pwdlib."""

    def __init__(self) -> None:
        """Сохраняет зависимости и настройки компонента."""
        self._password_hasher = pwdlib.PasswordHash.recommended()

    def hash(self, plain_password: str) -> str:
        """Вычисляет хеш открытого пароля для хранения.

        Args:
            plain_password: Открытый пароль для вычисления или проверки хеша.

        Returns:
            Строка хеша с солью и параметрами алгоритма.
        """
        return self._password_hasher.hash(plain_password)

    def verify(self, plain_password: str, password_hash: str) -> bool:
        """Сравнивает открытый пароль с сохранённым хешем.

        Args:
            plain_password: Открытый пароль для вычисления или проверки хеша.
            password_hash: Сохранённая строка хеша пароля.

        Returns:
            True, если пароль соответствует хешу; иначе False.
        """
        return self._password_hasher.verify(
            password=plain_password,
            hash=password_hash,
        )
