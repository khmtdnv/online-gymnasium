from collections.abc import Callable
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from analytics_service.api.audit import router as audit_router
from analytics_service.api.dependencies import get_workload_repository
from analytics_service.application.ports.workload_repository import WorkloadRepository
from analytics_service.application.workload import ClassDailyWorkload


def create_app(
    repository_factory: Callable[[], WorkloadRepository],
    *,
    audit_repository_factory: Callable | None = None,
    audit_service_token: str | None = None,
) -> FastAPI:
    """Собирает HTTP-приложение с переданными зависимостями.

    Args:
        repository_factory: Фабрика репозитория дневной нагрузки.

    Returns:
        Приложение FastAPI с маршрутами и зависимостями в app.state.
    """
    app = FastAPI()
    app.state.workload_repository_factory = repository_factory
    app.state.audit_repository_factory = audit_repository_factory
    app.state.audit_service_token = audit_service_token
    app.include_router(audit_router)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        """Подтверждает, что HTTP-процесс отвечает на запросы.

        Returns:
            Статус ok без проверки внешних зависимостей.
        """
        return {"status": "ok"}

    @app.get("/workload")
    async def get_workload(
        class_id: Annotated[int, Query(gt=0)],
        day: date,
        repository: Annotated[WorkloadRepository, Depends(get_workload_repository)],
    ) -> ClassDailyWorkload:
        """Возвращает готовую дневную нагрузку класса.

        Args:
            class_id: ID класса, для которого выполняется операция.
            day: Календарная дата запрашиваемого дня.
            repository: Репозиторий готовой дневной нагрузки.

        Returns:
            Число плановых уроков, минуты и время обновления расчёта.

        Raises:
            HTTPException: Нет расчёта (404) или хранилище недоступно (503).
        """
        try:
            workload = await repository.get(
                class_id=class_id,
                day=day,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Analytics storage is unavailable",
            ) from exc

        if workload is None:
            raise HTTPException(
                status_code=404,
                detail="Workload was not found",
            )

        return workload

    return app
