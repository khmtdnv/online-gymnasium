"""Общий маршрутизатор HTTP-ручек сервиса."""

from fastapi import APIRouter, Depends

from gateway_service.api.analytics import router as analytics_router
from gateway_service.api.auth import router as auth_router
from gateway_service.api.backoffice import router as backoffice_router
from gateway_service.api.backoffice_analytics import (
    router as backoffice_analytics_router,
)
from gateway_service.api.backoffice_billing import router as backoffice_billing_router
from gateway_service.api.backoffice_identity import router as backoffice_identity_router
from gateway_service.api.billing import router as billing_router
from gateway_service.api.documents import router as documents_router
from gateway_service.api.health import router as health_router
from gateway_service.api.homework import router as homework_router
from gateway_service.api.homework_answers import router as homework_answers_router
from gateway_service.api.homework_files import router as homework_files_router
from gateway_service.api.homework_list import router as homework_list_router
from gateway_service.api.internal_users import router as internal_users_router
from gateway_service.api.my_schedule import router as my_schedule_router
from gateway_service.api.notifications import router as notifications_router
from gateway_service.api.pen import router as pen_router
from gateway_service.api.schedule_admin import router as schedule_admin_router
from gateway_service.api.student_homework import router as student_homework_router
from gateway_service.api.teacher_lessons import router as teacher_lessons_router
from gateway_service.api.tuition_access import require_learning_access
from gateway_service.api.user_profiles import router as profiles_router

router = APIRouter()
router.include_router(billing_router)
router.include_router(documents_router)
router.include_router(notifications_router)
router.include_router(analytics_router)
router.include_router(pen_router)
router.include_router(auth_router)
router.include_router(health_router)
router.include_router(backoffice_router)
router.include_router(backoffice_analytics_router)
router.include_router(backoffice_billing_router)
router.include_router(backoffice_identity_router)
router.include_router(internal_users_router)
router.include_router(profiles_router)
router.include_router(homework_router)
router.include_router(
    homework_answers_router, dependencies=[Depends(require_learning_access)]
)
router.include_router(
    homework_files_router, dependencies=[Depends(require_learning_access)]
)
router.include_router(
    student_homework_router, dependencies=[Depends(require_learning_access)]
)
router.include_router(teacher_lessons_router)
router.include_router(
    my_schedule_router, dependencies=[Depends(require_learning_access)]
)
router.include_router(schedule_admin_router)
router.include_router(
    homework_list_router, dependencies=[Depends(require_learning_access)]
)
