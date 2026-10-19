"""Сборка приложения с явно переданными зависимостями."""

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from homework_service.api.errors import HomeworkHTTPError
from homework_service.api.health import router
from homework_service.api.homework import router as homework_router
from homework_service.api.student_reads import router as student_reads_router
from homework_service.api.teacher_lessons import router as teacher_lessons_router
from homework_service.application.homework import CreateHomeworkHandler
from homework_service.application.student_reads import (
    GetStudentHomeworkHandler,
    ListStudentHomeworkHandler,
)
from homework_service.application.teacher_lessons import GetTeacherLessonHandler
from homework_service.config import HomeworkSettings
from homework_service.infrastructure.database import (
    check_database,
    create_session_factory,
)
from homework_service.infrastructure.journal_client import HttpJournalReader
from homework_service.infrastructure.schedule_client import HttpScheduleReader
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


def create_app(
    settings: HomeworkSettings,
    engine: AsyncEngine,
    *,
    database_probe: Callable[[AsyncEngine], Awaitable[None]] = check_database,
    create_homework_handler: CreateHomeworkHandler | None = None,
    list_student_homework_handler: ListStudentHomeworkHandler | None = None,
    get_student_homework_handler: GetStudentHomeworkHandler | None = None,
    get_teacher_lesson_handler: GetTeacherLessonHandler | None = None,
) -> FastAPI:
    """Собирает health и закрытое создание с управляемыми ресурсами.

    Args:
        settings: Настройки текущего процесса.
        engine: Engine собственной базы.
        database_probe: Проверка готовности; заменяется в тестах без БД.
        create_homework_handler: Готовый сценарий; иначе собирается при старте.
        list_student_homework_handler: Подмена чтения страницы для тестов.
        get_student_homework_handler: Подмена чтения одного задания для тестов.
        get_teacher_lesson_handler: Подмена сценария карточки своего урока.

    Returns:
        Приложение с health-ручками и закрытием engine при остановке.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            async with AsyncExitStack() as stack:
                if any(
                    handler is None
                    for handler in (
                        create_homework_handler,
                        list_student_homework_handler,
                        get_student_homework_handler,
                        get_teacher_lesson_handler,
                    )
                ) and all(
                    (
                        settings.gateway_service_token,
                        settings.schedule_base_url,
                        settings.schedule_service_token,
                        settings.journal_base_url,
                        settings.journal_service_token,
                    )
                ):
                    schedule = await stack.enter_async_context(
                        httpx.AsyncClient(
                            base_url=settings.schedule_base_url,
                            timeout=5.0,
                            follow_redirects=False,
                        )
                    )
                    journal = await stack.enter_async_context(
                        httpx.AsyncClient(
                            base_url=settings.journal_base_url,
                            timeout=5.0,
                            follow_redirects=False,
                        )
                    )
                    session_factory = create_session_factory(engine)
                    schedule_reader = HttpScheduleReader(
                        schedule, settings.schedule_service_token
                    )
                    journal_reader = HttpJournalReader(
                        journal, settings.journal_service_token
                    )

                    def uow_factory() -> SqlAlchemyUnitOfWork:
                        return SqlAlchemyUnitOfWork(session_factory)

                    app.state.create_homework_handler = (
                        create_homework_handler
                        or CreateHomeworkHandler(
                            uow_factory=uow_factory,
                            schedule_reader=schedule_reader,
                            journal_reader=journal_reader,
                            clock=lambda: datetime.now(UTC),
                        )
                    )
                    app.state.list_student_homework_handler = (
                        list_student_homework_handler
                        or ListStudentHomeworkHandler(
                            uow_factory,
                            journal_reader,
                            schedule_reader,
                        )
                    )
                    app.state.get_student_homework_handler = (
                        get_student_homework_handler
                        or GetStudentHomeworkHandler(
                            uow_factory,
                            journal_reader,
                            schedule_reader,
                        )
                    )
                    app.state.get_teacher_lesson_handler = (
                        get_teacher_lesson_handler
                        or GetTeacherLessonHandler(
                            uow_factory, schedule_reader, journal_reader
                        )
                    )
                yield
        finally:
            app.state.create_homework_handler = create_homework_handler
            app.state.list_student_homework_handler = list_student_homework_handler
            app.state.get_student_homework_handler = get_student_homework_handler
            app.state.get_teacher_lesson_handler = get_teacher_lesson_handler
            await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.exception_handler(HomeworkHTTPError)
    async def handle_homework_error(request, exc: HomeworkHTTPError):
        """Возвращает стабильный код без деталей источника отказа."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.detail}},
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
        )

    app.state.create_homework_handler = create_homework_handler
    app.state.list_student_homework_handler = list_student_homework_handler
    app.state.get_student_homework_handler = get_student_homework_handler
    app.state.get_teacher_lesson_handler = get_teacher_lesson_handler
    app.state.engine = engine
    app.state.settings = settings
    app.state.database_probe = database_probe
    app.include_router(router)
    app.include_router(homework_router)
    app.include_router(student_reads_router)
    app.include_router(teacher_lessons_router)
    return app
