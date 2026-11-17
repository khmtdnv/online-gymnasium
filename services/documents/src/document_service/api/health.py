from fastapi import APIRouter

router = APIRouter()


@router.get("/health/live")
def health_live() -> dict[str, str]:
    """Подтверждает, что HTTP-процесс отвечает на запросы.

    Returns:
        Статус ok без проверки внешних зависимостей.
    """
    return {"status": "ok"}
