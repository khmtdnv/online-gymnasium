"""Сборка приложения с явно переданными зависимостями."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, BinaryIO
from uuid import UUID

import httpx
from anyio import CapacityLimiter
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from homework_service.api.errors import HomeworkHTTPError
from homework_service.api.health import router
from homework_service.api.homework import router as homework_router
from homework_service.api.homework_answer_files import (
    router as homework_answer_files_router,
)
from homework_service.api.homework_answers import router as homework_answers_router
from homework_service.api.homework_files import router as homework_files_router
from homework_service.api.homework_list import router as homework_list_router
from homework_service.api.student_lessons import router as student_lessons_router
from homework_service.api.student_reads import router as student_reads_router
from homework_service.api.teacher_lessons import router as teacher_lessons_router
from homework_service.application import file_access
from homework_service.application.homework import CreateHomeworkHandler
from homework_service.application.homework_answer_files import (
    HomeworkAnswerFilesHandler,
)
from homework_service.application.homework_answers import (
    ReadHomeworkAnswersHandler,
    ReviewHomeworkAnswerHandler,
    SubmitHomeworkAnswerHandler,
)
from homework_service.application.homework_files import (
    GetHomeworkFileHandler,
    HomeworkFileResult,
    UploadHomeworkFileHandler,
)
from homework_service.application.homework_list import ListMyHomeworkHandler
from homework_service.application.student_lessons import GetStudentLessonHandler
from homework_service.application.student_reads import (
    GetStudentHomeworkHandler,
    ListStudentHomeworkHandler,
)
from homework_service.application.teacher_lessons import GetTeacherLessonHandler
from homework_service.config import HomeworkSettings
from homework_service.domain.homework import Homework
from homework_service.domain.homework_file import HomeworkFile
from homework_service.infrastructure.database import (
    check_database,
    create_session_factory,
)
from homework_service.infrastructure.journal_client import HttpJournalReader
from homework_service.infrastructure.schedule_client import HttpScheduleReader
from homework_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

if TYPE_CHECKING:
    from homework_service.infrastructure.minio_file_storage import MinioFileStorage


def create_file_storage(settings: HomeworkSettings) -> MinioFileStorage | None:
    """Подключает SDK только при включённом хранилище.

    Args:
        settings: Настройки процесса, включая необязательный MinIO.

    Returns:
        Адаптер приватного bucket либо None без настроек файлов.
    """
    if not all(
        (
            settings.minio_endpoint,
            settings.minio_bucket,
            settings.minio_access_key,
            settings.minio_secret_key,
        )
    ):
        return None
    from homework_service.infrastructure.minio_file_storage import (
        create_file_storage as build_storage,
    )

    return build_storage(settings)


def create_app(
    settings: HomeworkSettings,
    engine: AsyncEngine,
    *,
    database_probe: Callable[[AsyncEngine], Awaitable[None]] = check_database,
    create_homework_handler: CreateHomeworkHandler | None = None,
    list_student_homework_handler: ListStudentHomeworkHandler | None = None,
    get_student_homework_handler: GetStudentHomeworkHandler | None = None,
    get_teacher_lesson_handler: GetTeacherLessonHandler | None = None,
    upload_homework_file_handler: UploadHomeworkFileHandler | None = None,
    get_homework_file_handler: GetHomeworkFileHandler | None = None,
    submit_homework_answer_handler: SubmitHomeworkAnswerHandler | None = None,
    review_homework_answer_handler: ReviewHomeworkAnswerHandler | None = None,
    read_homework_answers_handler: ReadHomeworkAnswersHandler | None = None,
    homework_answer_files_handler: HomeworkAnswerFilesHandler | None = None,
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
        upload_homework_file_handler: Подмена сценария загрузки вложения.
        get_homework_file_handler: Подмена проверки доступа перед скачиванием.
        submit_homework_answer_handler: Подмена сдачи ученической работы.
        review_homework_answer_handler: Подмена проверки работы преподавателем.
        read_homework_answers_handler: Подмена чтения попыток и оценок.
        homework_answer_files_handler: Подмена доступа к приватным файлам ответа.

    Returns:
        Приложение с health-ручками и закрытием engine при остановке.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            async with AsyncExitStack() as stack:
                # В общем MinIO-пуле четыре соединения: оставляем два для
                # загрузок, чтобы медленные скачивания не заняли весь пул.
                app.state.file_download_limiter = CapacityLimiter(2)
                app.state.file_storage = create_file_storage(settings)
                if app.state.file_storage is not None:
                    stack.callback(app.state.file_storage.close)
                if (
                    any(
                        handler is None
                        for handler in (
                            create_homework_handler,
                            list_student_homework_handler,
                            get_student_homework_handler,
                            get_teacher_lesson_handler,
                            get_homework_file_handler,
                            submit_homework_answer_handler,
                            review_homework_answer_handler,
                            read_homework_answers_handler,
                            homework_answer_files_handler,
                        )
                    )
                    or (
                        upload_homework_file_handler is None
                        and app.state.file_storage is not None
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

                    app.state.get_student_lesson_handler = GetStudentLessonHandler(
                        uow_factory, schedule_reader, journal_reader
                    )
                    app.state.list_my_homework_handler = ListMyHomeworkHandler(
                        uow_factory, journal_reader, schedule_reader
                    )

                    app.state.submit_homework_answer_handler = (
                        submit_homework_answer_handler
                        or SubmitHomeworkAnswerHandler(
                            uow_factory, journal_reader, schedule_reader
                        )
                    )
                    app.state.review_homework_answer_handler = (
                        review_homework_answer_handler
                        or ReviewHomeworkAnswerHandler(
                            uow_factory, journal_reader, schedule_reader
                        )
                    )
                    app.state.read_homework_answers_handler = (
                        read_homework_answers_handler
                        or ReadHomeworkAnswersHandler(
                            uow_factory, journal_reader, schedule_reader
                        )
                    )
                    upload_limiter = CapacityLimiter(2)
                    app.state.homework_answer_files_handler = (
                        homework_answer_files_handler
                        or HomeworkAnswerFilesHandler(
                            uow_factory,
                            journal_reader,
                            schedule_reader,
                            app.state.file_storage,
                            upload_limiter,
                        )
                    )

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
                    app.state.get_homework_file_handler = (
                        get_homework_file_handler
                        or GetHomeworkFileHandler(
                            uow_factory, journal_reader, schedule_reader
                        )
                    )
                    if (
                        upload_homework_file_handler is None
                        and app.state.file_storage is not None
                    ):
                        # Проверки содержимого нужны только включённой загрузке,
                        # а не соседнему Gateway с внедрёнными JSON-сценариями.
                        from homework_service.infrastructure import file_upload

                        storage = app.state.file_storage
                        limiter = upload_limiter

                        async def check_teacher_access(
                            teacher_id: UUID, homework: Homework
                        ) -> None:
                            """Проверяет преподавателя через текущие данные владельцев."""
                            await file_access.check_teacher_access(
                                teacher_id, homework, schedule_reader, journal_reader
                            )

                        async def save_file(
                            file: HomeworkFile, stream: BinaryIO
                        ) -> tuple[str, datetime]:
                            """Ограничивает число одновременных проверок и загрузок."""
                            return await file_upload.save_file(
                                file, stream, uow_factory, storage, limiter=limiter
                            )

                        async def finish_upload(
                            file: HomeworkFile, storage_key: str, started_at: datetime
                        ) -> HomeworkFileResult:
                            """Фиксирует готовность вложения короткой транзакцией."""
                            return await file_upload.finish_upload(
                                file, storage_key, started_at, uow_factory, storage
                            )

                        app.state.upload_homework_file_handler = (
                            UploadHomeworkFileHandler(
                                uow_factory,
                                check_teacher_access,
                                save_file,
                                finish_upload,
                            )
                        )
                yield
        finally:
            app.state.file_storage = None
            app.state.get_student_lesson_handler = None
            app.state.list_my_homework_handler = None
            app.state.upload_homework_file_handler = upload_homework_file_handler
            app.state.get_homework_file_handler = get_homework_file_handler
            app.state.create_homework_handler = create_homework_handler
            app.state.list_student_homework_handler = list_student_homework_handler
            app.state.get_student_homework_handler = get_student_homework_handler
            app.state.get_teacher_lesson_handler = get_teacher_lesson_handler
            app.state.submit_homework_answer_handler = submit_homework_answer_handler
            app.state.review_homework_answer_handler = review_homework_answer_handler
            app.state.read_homework_answers_handler = read_homework_answers_handler
            app.state.homework_answer_files_handler = homework_answer_files_handler
            await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.get_student_lesson_handler = None
    app.state.list_my_homework_handler = None
    app.include_router(student_lessons_router)
    app.include_router(homework_list_router)

    @app.exception_handler(HomeworkHTTPError)
    async def handle_homework_error(request, exc: HomeworkHTTPError):
        """Возвращает стабильный код без деталей источника отказа."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.detail}},
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
        )

    app.state.create_homework_handler = create_homework_handler
    app.state.upload_homework_file_handler = upload_homework_file_handler
    app.state.get_homework_file_handler = get_homework_file_handler
    app.state.file_download_limiter = CapacityLimiter(2)
    app.state.file_storage = None
    app.state.list_student_homework_handler = list_student_homework_handler
    app.state.get_student_homework_handler = get_student_homework_handler
    app.state.get_teacher_lesson_handler = get_teacher_lesson_handler
    app.state.submit_homework_answer_handler = submit_homework_answer_handler
    app.state.review_homework_answer_handler = review_homework_answer_handler
    app.state.read_homework_answers_handler = read_homework_answers_handler
    app.state.homework_answer_files_handler = homework_answer_files_handler
    app.state.engine = engine
    app.state.settings = settings
    app.state.database_probe = database_probe
    app.include_router(router)
    app.include_router(homework_router)
    app.include_router(homework_answers_router)
    app.include_router(homework_answer_files_router)
    app.include_router(homework_files_router)
    app.include_router(student_reads_router)
    app.include_router(teacher_lessons_router)
    return app
