"""Защищённые операции над назначениями преподавателей."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from journal_service.api.dependencies import (
    get_assign_teacher_handler,
    get_teacher_classes_handler,
    get_unassign_teacher_handler,
)
from journal_service.api.security import (
    RequireServicePermission,
    get_teacher_assignment_actor_id,
)
from journal_service.application.classes import ClassResult
from journal_service.application.teacher_classes import (
    AssignTeacherToClassCommand,
    AssignTeacherToClassHandler,
    ListClassesForTeacherHandler,
    ListClassesForTeacherQuery,
    UnassignTeacherFromClassCommand,
    UnassignTeacherFromClassHandler,
)

router = APIRouter(prefix="/internal/teachers", include_in_schema=False)
ClassId = Annotated[int, Path(ge=1, le=2147483647)]


@router.put(
    "/{teacher_id}/classes/{class_id}", status_code=201, response_class=Response
)
async def assign_teacher(
    teacher_id: UUID,
    class_id: ClassId,
    actor_id: Annotated[str, Depends(get_teacher_assignment_actor_id)],
    handler: Annotated[
        AssignTeacherToClassHandler, Depends(get_assign_teacher_handler)
    ],
) -> Response:
    """Назначает учителя: 201 новая связь, 204 повтор.

    Args:
        teacher_id: UUID преподавателя из адреса.
        class_id: Положительный ID класса.
        actor_id: Проверенный ID сотрудника от Backoffice.
        handler: Сценарий с проверкой Gateway.

    Returns:
        Пустой ответ после успешного завершения транзакции.
    """
    result = await handler.handle(
        AssignTeacherToClassCommand(teacher_id=teacher_id, class_id=class_id)
    )
    return Response(status_code=201 if result.created else 204)


@router.delete(
    "/{teacher_id}/classes/{class_id}", status_code=204, response_class=Response
)
async def unassign_teacher(
    teacher_id: UUID,
    class_id: ClassId,
    actor_id: Annotated[str, Depends(get_teacher_assignment_actor_id)],
    handler: Annotated[
        UnassignTeacherFromClassHandler, Depends(get_unassign_teacher_handler)
    ],
) -> Response:
    """Снимает назначение, даже если пользователя больше нет в Gateway.

    Args:
        teacher_id: UUID преподавателя.
        class_id: ID класса.
        actor_id: Проверенный инициатор от Backoffice.
        handler: Сценарий удаления связи.

    Returns:
        Пустой 204, в том числе при повторе.
    """
    await handler.handle(
        UnassignTeacherFromClassCommand(teacher_id=teacher_id, class_id=class_id)
    )
    return Response(status_code=204)


@router.get(
    "/{teacher_id}/classes",
    response_model=list[ClassResult],
    dependencies=[Depends(RequireServicePermission("teacher-classes:read"))],
)
async def list_teacher_classes(
    teacher_id: UUID,
    handler: Annotated[
        ListClassesForTeacherHandler, Depends(get_teacher_classes_handler)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> list[ClassResult]:
    """Читает назначения, не требуя write-прав или actor-заголовка.

    Args:
        teacher_id: UUID преподавателя.
        handler: Сценарий чтения классов.
        limit: Размер страницы.
        offset: Число пропускаемых записей.

    Returns:
        Назначенные классы; пустой список допустим.
    """
    return await handler.handle(
        ListClassesForTeacherQuery(teacher_id=teacher_id, limit=limit, offset=offset)
    )
