"""Уборка не трогает используемые объекты, свежие попытки и строки БД."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from homework_service.cleanup_files import cleanup_files

NOW = datetime(2026, 10, 20, tzinfo=UTC)
KEY = "homework/1/files/8/" + "a" * 32


def setup(objects, *, used=False, unavailable=False):
    state = {"open": False}
    repo = SimpleNamespace(
        get_by_id=AsyncMock(
            return_value=SimpleNamespace(storage_key=KEY) if used else None
        ),
        get_current_time=AsyncMock(return_value=NOW),
    )

    @asynccontextmanager
    async def uow():
        if unavailable:
            raise OSError("database unavailable")
        state["open"] = True
        try:
            yield SimpleNamespace(files=repo)
        finally:
            state["open"] = False

    def delete(key):
        assert not state["open"]

    storage = SimpleNamespace(
        list_objects=Mock(return_value=iter(objects)), delete=Mock(side_effect=delete)
    )
    return storage, uow, repo


def test_only_old_unreferenced_object_is_deleted_and_row_is_not_removed():
    storage, uow, repo = setup([(KEY, NOW - timedelta(hours=25))])
    assert asyncio.run(cleanup_files(storage, uow)) == 1
    storage.list_objects.assert_called_once_with("homework/")
    storage.delete.assert_called_once_with(KEY)
    repo.get_by_id.assert_awaited_once_with(8)


@pytest.mark.parametrize("used", [True, False])
def test_used_key_and_fresh_or_exactly_24h_object_are_preserved(used):
    objects = (
        [(KEY, NOW - timedelta(hours=25))]
        if used
        else [(KEY, NOW - timedelta(hours=1)), (KEY, NOW - timedelta(hours=24))]
    )
    storage, uow, _ = setup(objects, used=used)
    assert asyncio.run(cleanup_files(storage, uow)) == 0
    storage.delete.assert_not_called()


def test_unavailable_database_never_authorizes_delete():
    storage, uow, _ = setup([(KEY, NOW - timedelta(hours=25))], unavailable=True)
    with pytest.raises(OSError):
        asyncio.run(cleanup_files(storage, uow))
    storage.delete.assert_not_called()


@pytest.mark.parametrize(
    "key",
    [
        "other/1",
        "homework/1/files/8/not-an-attempt",
        "homework/0/files/8/" + "a" * 32,
        "homework/1/files/2147483648/" + "a" * 32,
    ],
)
def test_unknown_names_and_foreign_prefix_are_never_deleted(key):
    storage, uow, repo = setup([(key, NOW - timedelta(hours=25))])
    assert asyncio.run(cleanup_files(storage, uow)) == 0
    storage.delete.assert_not_called()
    repo.get_by_id.assert_not_awaited()


def test_every_candidate_reads_a_fresh_uow_and_preserves_a_committed_winner():
    other = "homework/1/files/8/" + "b" * 32
    storage, uow, repo = setup(
        [(other, NOW - timedelta(hours=25)), (KEY, NOW - timedelta(hours=25))],
        used=True,
    )
    assert asyncio.run(cleanup_files(storage, uow)) == 1
    storage.delete.assert_called_once_with(other)
    assert repo.get_by_id.await_count == 2


def test_future_storage_clock_is_not_an_old_object():
    storage, uow, _ = setup([(KEY, NOW + timedelta(hours=25))])
    assert asyncio.run(cleanup_files(storage, uow)) == 0
    storage.delete.assert_not_called()
