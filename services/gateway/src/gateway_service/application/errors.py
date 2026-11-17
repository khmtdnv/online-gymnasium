class ApplicationException(Exception):
    """Базовая ошибка сценария приложения."""


class AuthenticationError(ApplicationException):
    """Учётные данные или токен не позволяют подтвердить пользователя."""


class EmailAlreadyExistsError(ApplicationException):
    """Пользователь с таким email уже существует."""


class UserNotFoundError(ApplicationException):
    """Один из пользователей, необходимых для операции, не найден."""


class InvalidParentStudentRolesError(ApplicationException):
    """Для связи нужны пользователь-родитель и пользователь-ученик."""
