from fastapi import Request

from analytics_service.application.ports.workload_repository import WorkloadRepository


def get_workload_repository(request: Request) -> WorkloadRepository:
    """Создаёт репозиторий нагрузки через фабрику приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Репозиторий для выполнения запроса.
    """
    return request.app.state.workload_repository_factory()
