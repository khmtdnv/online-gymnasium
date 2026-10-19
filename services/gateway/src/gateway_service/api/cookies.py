from fastapi import Response

REFRESH_COOKIE_KEY = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(
    response: Response, token: str, max_age: int, secure: bool
) -> None:
    """Записывает refresh-токен в HttpOnly-cookie с общим путём.

    Args:
        response: HTTP-ответ для добавления заголовка Set-Cookie.
        token: Строка выпущенного refresh-токена.
        max_age: Срок хранения cookie в секундах.
        secure: Ограничить отправку cookie защищённым соединением.
    """
    response.set_cookie(
        key=REFRESH_COOKIE_KEY,
        value=token,
        max_age=max_age,
        path=REFRESH_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response, secure: bool) -> None:
    """Удаляет refresh-cookie с теми же именем и путём, что при создании.

    Args:
        response: HTTP-ответ для отправки просроченной cookie браузеру.
        secure: Флаг Secure, согласованный с настройкой создания cookie.
    """
    response.delete_cookie(
        key=REFRESH_COOKIE_KEY, path=REFRESH_COOKIE_PATH, secure=secure
    )
