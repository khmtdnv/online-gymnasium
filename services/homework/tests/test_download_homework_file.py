"""Файл доступен по текущим правам, а не по известному ID или старой роли."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    HomeworkNotFoundError,
    OwnerLookupUnavailableError,
)
from homework_service.domain.homework_file import HomeworkFile
from tests.test_homework_files import file_input
from tests.test_student_reads import homework, lesson


def build(
    *,
    current_class=7,
    assigned=True,
    source_teacher=2,
    due_teacher=3,
    ready=True,
    found=True,
    file_parent=1,
    source_class=7,
    failure=None,
):
    from homework_service.application.homework_files import GetHomeworkFileHandler

    state = {"active": False, "class_id": current_class}
    parent = homework(
        1, issued_lesson_id=11, due_lesson_id=22, manual_due_datetime=None
    )
    file = HomeworkFile(
        id=8,
        homework_id=file_parent,
        **file_input(),
        upload_status="ready" if ready else "pending",
        storage_key="homework/private" if ready else None,
    )

    async def get_parent(id):
        return parent if found else None

    async def get_file(id):
        return file

    @asynccontextmanager
    async def uow():
        state["active"] = True
        try:
            yield SimpleNamespace(
                homeworks=SimpleNamespace(get_by_id=get_parent),
                files=SimpleNamespace(get_by_id=get_file),
            )
        finally:
            state["active"] = False

    async def current(user_id):
        assert not state["active"]
        if failure:
            raise failure
        return state["class_id"]

    async def is_assigned(user_id, class_id):
        assert not state["active"]
        return assigned

    async def get_lessons(ids):
        assert not state["active"]
        if failure:
            raise failure
        return {
            id: lesson(
                id=id,
                class_id=source_class,
                teacher_id=UUID(int=source_teacher if id == 11 else due_teacher),
            )
            for id in ids
        }

    return GetHomeworkFileHandler(
        uow,
        SimpleNamespace(get_current_class_id=current, is_teacher_assigned=is_assigned),
        SimpleNamespace(get_lessons=get_lessons),
    ), state


def run(handler, *, role="student", user=1):
    from homework_service.application.homework_files import GetHomeworkFileQuery

    return asyncio.run(
        handler.handle(
            GetHomeworkFileQuery(
                user_id=UUID(int=user), role=role, homework_id=1, file_id=8
            )
        )
    )


def test_student_transfer_revokes_previously_known_file_id():
    handler, state = build()
    assert run(handler).id == 8
    state["class_id"] = 8
    with pytest.raises(HomeworkNotFoundError):
        run(handler)


@pytest.mark.parametrize("user", [2, 3])
def test_teacher_can_download_from_own_source_or_due_lesson(user):
    handler, _ = build()
    assert run(handler, role="teacher", user=user).upload_status == "ready"


@pytest.mark.parametrize(
    "changes", [{"assigned": False}, {"source_teacher": 4, "due_teacher": 5}]
)
def test_teacher_without_current_assignment_or_own_lesson_cannot_download(changes):
    handler, _ = build(**changes)
    with pytest.raises(HomeworkAccessDeniedError):
        run(handler, role="teacher", user=2)


@pytest.mark.parametrize(
    "changes", [{"found": False}, {"file_parent": 99}, {"current_class": None}]
)
def test_missing_or_foreign_file_is_not_found(changes):
    handler, _ = build(**changes)
    with pytest.raises(HomeworkNotFoundError):
        run(handler)


def test_pending_file_has_a_distinct_not_ready_error():
    from homework_service.application.ports.errors import HomeworkFileNotReadyError

    handler, _ = build(ready=False)
    with pytest.raises(HomeworkFileNotReadyError):
        run(handler)


@pytest.mark.parametrize("role", ["student", "teacher"])
def test_owner_failure_is_not_converted_into_permission_or_absence(role):
    handler, _ = build(failure=OwnerLookupUnavailableError())
    with pytest.raises(OwnerLookupUnavailableError):
        run(handler, role=role, user=2)


def test_incompatible_teacher_lesson_cannot_authorize_download():
    handler, _ = build(source_class=8)
    with pytest.raises(OwnerLookupUnavailableError):
        run(handler, role="teacher", user=2)
