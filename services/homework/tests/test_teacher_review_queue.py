from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from homework_service.application.homework_answers import ReadHomeworkAnswersHandler
from homework_service.application.ports.errors import (
    HomeworkAccessDeniedError,
    OwnerLookupUnavailableError,
)


class FakeUow:
    def __init__(self, candidates):
        self.answers = SimpleNamespace(
            review_candidates=AsyncMock(return_value=candidates)
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def candidate(number):
    answer = SimpleNamespace(
        id=number,
        student_id=UUID(int=number),
        status="submitted",
        submitted_at=datetime.now(UTC),
    )
    return (answer, number, number, number, number, "Задание")


@pytest.mark.anyio
async def test_queue_filters_by_authoritative_access_and_preserves_cursor():
    uow = FakeUow([candidate(i) for i in range(1, 102)])
    handler = ReadHomeworkAnswersHandler(lambda: uow, None, None)

    async def authorize(user_id, role, homework_id):
        if homework_id % 2 == 0:
            raise HomeworkAccessDeniedError

    handler.authorize = authorize
    page = await handler.review_queue(UUID(int=900), 0)
    assert [item.answer_id for item in page.items] == list(range(1, 101, 2))
    assert page.next_cursor == 100


@pytest.mark.anyio
async def test_queue_does_not_hide_unavailable_access_checks():
    handler = ReadHomeworkAnswersHandler(lambda: FakeUow([candidate(1)]), None, None)
    handler.authorize = AsyncMock(side_effect=OwnerLookupUnavailableError())
    with pytest.raises(OwnerLookupUnavailableError):
        await handler.review_queue(UUID(int=900), 0)


@pytest.fixture
def anyio_backend():
    return "asyncio"
