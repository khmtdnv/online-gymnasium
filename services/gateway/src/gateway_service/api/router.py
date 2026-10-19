"""Общий маршрутизатор HTTP-ручек сервиса."""

from fastapi import APIRouter

from gateway_service.api.auth import router as auth_router
from gateway_service.api.backoffice import router as backoffice_router
from gateway_service.api.health import router as health_router
from gateway_service.api.homework import router as homework_router
from gateway_service.api.internal_users import router as internal_users_router
from gateway_service.api.student_homework import router as student_homework_router
from gateway_service.api.teacher_lessons import router as teacher_lessons_router
from gateway_service.api.user_profiles import router as profiles_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(health_router)
router.include_router(backoffice_router)
router.include_router(internal_users_router)
router.include_router(profiles_router)
router.include_router(homework_router)
router.include_router(student_homework_router)
router.include_router(teacher_lessons_router)
