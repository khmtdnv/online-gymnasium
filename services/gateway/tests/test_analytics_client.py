"""Недостоверный ответ владельца не превращается в отчёт с выдуманной оценкой."""

import asyncio
from datetime import date

import httpx
import pytest


def test_analytics_client_rejects_invalid_average():
    from gateway_service.application.analytics import ProgressQuery
    from gateway_service.infrastructure.analytics_client import (
        AnalyticsClient,
        AnalyticsUnavailableError,
    )

    async def run():
        def response(request):
            assert request.headers["Authorization"] == "Bearer only-read"
            return httpx.Response(
                200,
                json=[
                    {
                        "student_id": "00000000-0000-0000-0000-000000000001",
                        "subject_id": 3,
                        "graded_count": 1,
                        "average_grade": 0,
                    }
                ],
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(response), base_url="http://analytics"
        ) as http:
            with pytest.raises(AnalyticsUnavailableError):
                await AnalyticsClient(http, "only-read").get_progress(
                    ProgressQuery(
                        class_id=7,
                        date_from=date(2026, 10, 1),
                        date_to=date(2026, 10, 22),
                    )
                )

    asyncio.run(run())
