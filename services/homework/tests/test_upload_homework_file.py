"""Учебная логика: связать чтение, проверку прав и готовые помощники загрузки."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkNotFoundError,
)
from homework_service.domain.homework import Homework
from homework_service.domain.homework_file import HomeworkFile
from tests.test_domain_homework import data
from tests.test_homework_files import file_input

pytestmark = pytest.mark.learning
TEACHER = UUID(int=1)
NOW = datetime(2026, 10, 19, tzinfo=UTC)


def build_handler(
    *,
    parent_exists=True,
    file_exists=True,
    file_parent=51,
    ready=False,
    allowed=True,
    failure=None,
):
    from homework_service.application.homework_files import (
        HomeworkFileResult,
        UploadHomeworkFileHandler,
    )

    homework = Homework(**data(id=51, author_id=TEACHER, created_at=NOW))
    file = HomeworkFile(
        homework_id=file_parent,
        id=8,
        **file_input(),
        upload_status="ready" if ready else "pending",
        storage_key="homework/51/files/8/existing" if ready else None,
    )
    events = []
    active = []

    async def get_homework(homework_id):
        return homework if homework_id == 51 and parent_exists else None

    async def get_file(file_id):
        return file if file_id == 8 and file_exists else None

    @asynccontextmanager
    async def uow():
        active.append(True)
        try:
            yield SimpleNamespace(
                homeworks=SimpleNamespace(get_by_id=get_homework),
                files=SimpleNamespace(get_by_id=get_file),
            )
        finally:
            active.pop()

    async def check_teacher_access(teacher_id, requested_homework):
        assert not active, "close the read UoW before calling owner services"
        assert teacher_id == TEACHER and requested_homework.id == 51
        events.append("access")
        if not allowed:
            raise HomeworkAccessDeniedError

    async def save_file(requested_file, stream):
        assert not active and requested_file == file
        assert events == ["access"], "check permission before uploading bytes"
        events.append("save")
        if failure is not None:
            raise failure
        return "homework/51/files/8/new", NOW

    async def finish_upload(requested_file, storage_key, started_at):
        assert not active and requested_file == file
        assert storage_key == "homework/51/files/8/new" and started_at == NOW
        assert events == ["access", "save"]
        events.append("finish")
        return HomeworkFileResult.from_file(
            replace(file, upload_status="ready", storage_key=storage_key)
        )

    return UploadHomeworkFileHandler(
        uow, check_teacher_access, save_file, finish_upload
    ), events


def command():
    from homework_service.application.homework_files import UploadHomeworkFileCommand

    return UploadHomeworkFileCommand(teacher_id=TEACHER, homework_id=51, file_id=8)


@pytest.mark.parametrize(
    "changes",
    [
        {"parent_exists": False},
        {"file_exists": False},
        {"file_parent": 999},
    ],
)
def test_missing_or_foreign_file_does_not_call_access_or_storage(changes):
    handler, events = build_handler(**changes)
    with pytest.raises(HomeworkNotFoundError):
        asyncio.run(handler.handle(command(), BytesIO(b"data")))
    assert events == []


@pytest.mark.parametrize("ready", [False, True])
def test_permission_required_even_when_file_already_ready(ready):
    handler, events = build_handler(ready=ready, allowed=False)
    with pytest.raises(HomeworkAccessDeniedError):
        asyncio.run(handler.handle(command(), BytesIO(b"data")))
    assert events == ["access"]


def test_ready_file_returns_saved_metadata_without_reupload():
    handler, events = build_handler(ready=True)
    stream = BytesIO(b"not the old file")
    result = asyncio.run(handler.handle(command(), stream))
    assert (
        result.id == 8 and result.homework_id == 51 and result.upload_status == "ready"
    )
    assert events == ["access"] and stream.tell() == 0 and not stream.closed


def test_pending_file_is_saved_then_finalized_after_access_check():
    handler, events = build_handler()
    result = asyncio.run(handler.handle(command(), BytesIO(b"data")))
    assert result.id == 8 and result.upload_status == "ready"
    assert events == ["access", "save", "finish"]


@pytest.mark.parametrize(
    "failure", [ValueError("invalid file contents"), OSError("storage unavailable")]
)
def test_failed_validation_or_storage_does_not_mark_file_ready(failure):
    handler, events = build_handler(failure=failure)
    with pytest.raises(type(failure)):
        asyncio.run(handler.handle(command(), BytesIO(b"data")))
    assert events == ["access", "save"]
