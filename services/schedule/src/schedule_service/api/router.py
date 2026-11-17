"""Общий маршрутизатор HTTP-ручек сервиса."""

from fastapi import APIRouter

from schedule_service.api.calendar_lessons import router as calendar_router
from schedule_service.api.health import router as health_router
from schedule_service.api.homework_reads import router as homework_reads_router
from schedule_service.api.lessons import router as lessons_router
from schedule_service.api.teacher_lessons import router as teacher_lessons_router

router = APIRouter()

router.include_router(health_router)
router.include_router(calendar_router)
router.include_router(lessons_router)
router.include_router(homework_reads_router)
router.include_router(teacher_lessons_router)
