from fastapi import Request

from schedule_service.application.cancel_lesson import CancelLessonHandler
from schedule_service.application.create_lesson import CreateLessonHandler
from schedule_service.application.list_lessons import ListLessonsHandler
from schedule_service.application.update_lesson import UpdateLessonHandler


def get_create_lesson_handler(request: Request) -> CreateLessonHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return CreateLessonHandler(uow_factory=request.app.state.uow_factory)


def get_cancel_lesson_handler(request: Request) -> CancelLessonHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return CancelLessonHandler(uow_factory=request.app.state.uow_factory)


def get_update_lesson_handler(request: Request) -> UpdateLessonHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    return UpdateLessonHandler(uow_factory=request.app.state.uow_factory)


def get_list_lessons_handler(request: Request) -> ListLessonsHandler:
    """Собирает обработчик сценария из зависимостей приложения.

    Args:
        request: HTTP-запрос с зависимостями приложения в app.state.

    Returns:
        Обработчик с зависимостями текущего приложения.
    """
    settings = request.app.state.settings

    return ListLessonsHandler(
        uow_factory=request.app.state.uow_factory,
        cache=request.app.state.schedule_cache,
        schedule_cache_ttl_seconds=settings.schedule_cache_ttl_seconds,
        schedule_cache_lock_ttl_ms=settings.schedule_cache_lock_ttl_ms,
        schedule_cache_lock_retry_delay_ms=(
            settings.schedule_cache_lock_retry_delay_ms
        ),
        schedule_cache_lock_retry_limit=settings.schedule_cache_lock_retry_limit,
    )
