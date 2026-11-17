"""Низкоуровневые помощники не держат SQL-транзакцию во время записи байтов."""

import asyncio
import hashlib
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import pytest

from homework_service.domain.homework_file import HomeworkFile

NOW = datetime(2026, 10, 19, tzinfo=UTC)
CONTENT = "Решить упражнение".encode()


def pending_file():
    return HomeworkFile(
        id=8,
        homework_id=51,
        file_name="Задачи.txt",
        size_bytes=len(CONTENT),
        content_type="text/plain",
        content_sha256=hashlib.sha256(CONTENT).hexdigest(),
    )


class FileStorage:
    """In-memory байты с теми же side effects, без сети и скрытых commit."""

    def __init__(self, active):
        self.objects = {}
        self.active = active

    def put(self, storage_key, stream, size_bytes, content_type):
        assert not self.active, "network I/O must happen outside the SQL transaction"
        self.objects[storage_key] = stream.read(size_bytes)

    def delete(self, storage_key):
        assert not self.active
        self.objects.pop(storage_key, None)


def dependencies(
    *, ready=False, commit_unknown=False, database_down=False, expires=False
):
    active = []
    current = pending_file()
    if ready:
        current = replace(
            current, upload_status="ready", storage_key="homework/51/files/8/winner"
        )
    database = SimpleNamespace(current=current, commit_unknown=commit_unknown)

    class Files:
        async def get_current_time(self):
            return NOW

        async def mark_ready(self, file_id, storage_key, started_at):
            assert file_id == 8 and started_at == NOW
            if database.current.upload_status == "ready" or expires:
                return None
            database.current = replace(
                database.current, upload_status="ready", storage_key=storage_key
            )
            return database.current

        async def get_by_id(self, file_id):
            assert file_id == 8
            if database_down:
                raise OSError("database unavailable during recovery")
            return database.current

    @asynccontextmanager
    async def uow():
        active.append(True)
        try:
            yield SimpleNamespace(files=Files())
        finally:
            active.pop()
        if database.commit_unknown:
            database.commit_unknown = False
            raise OSError("commit response lost")

    return uow, FileStorage(active), database


def test_save_file_checks_bytes_and_closes_sql_before_minio():
    from homework_service.infrastructure.file_upload import save_file

    uow, storage, _ = dependencies()
    stream = BytesIO(CONTENT)
    key, started_at = asyncio.run(save_file(pending_file(), stream, uow, storage))
    assert key.startswith("homework/51/files/8/") and started_at == NOW
    assert storage.objects[key] == CONTENT and not stream.closed


def test_save_file_does_not_upload_different_bytes_with_same_metadata():
    from homework_service.infrastructure.file_upload import save_file

    uow, storage, _ = dependencies()
    with pytest.raises(ValueError):
        asyncio.run(save_file(pending_file(), BytesIO(b"different"), uow, storage))
    assert storage.objects == {}


def test_finish_returns_ready_metadata_only_after_commit():
    from homework_service.infrastructure.file_upload import finish_upload

    uow, storage, database = dependencies()
    key = "homework/51/files/8/attempt"
    storage.objects[key] = CONTENT
    result = asyncio.run(finish_upload(pending_file(), key, NOW, uow, storage))
    assert result.id == 8 and result.upload_status == "ready"
    assert database.current.storage_key == key and storage.objects[key] == CONTENT


def test_losing_upload_returns_winner_and_removes_only_own_unused_bytes():
    from homework_service.infrastructure.file_upload import finish_upload

    uow, storage, database = dependencies(ready=True)
    key = "homework/51/files/8/loser"
    storage.objects.update({key: CONTENT, database.current.storage_key: CONTENT})
    result = asyncio.run(finish_upload(pending_file(), key, NOW, uow, storage))
    assert result.upload_status == "ready" and result.id == 8
    assert key not in storage.objects
    assert storage.objects[database.current.storage_key] == CONTENT


def test_commit_response_loss_recovers_ready_file_without_deleting_it():
    from homework_service.infrastructure.file_upload import finish_upload

    uow, storage, database = dependencies(commit_unknown=True)
    key = "homework/51/files/8/attempt"
    storage.objects[key] = CONTENT
    result = asyncio.run(finish_upload(pending_file(), key, NOW, uow, storage))
    assert result.upload_status == "ready" and database.current.storage_key == key
    assert storage.objects[key] == CONTENT


def test_unknown_commit_and_failed_recovery_keep_potentially_referenced_object():
    from homework_service.infrastructure.file_upload import finish_upload

    uow, storage, database = dependencies(commit_unknown=True, database_down=True)
    key = "homework/51/files/8/attempt"
    storage.objects[key] = CONTENT
    with pytest.raises(OSError):
        asyncio.run(finish_upload(pending_file(), key, NOW, uow, storage))
    assert database.current.storage_key == key and storage.objects[key] == CONTENT


def test_expired_attempt_does_not_mark_pending_file_ready():
    from homework_service.infrastructure.file_upload import finish_upload

    uow, storage, database = dependencies(expires=True)
    key = "homework/51/files/8/expired"
    storage.objects[key] = CONTENT
    with pytest.raises(OSError):
        asyncio.run(finish_upload(pending_file(), key, NOW, uow, storage))
    assert (
        database.current.upload_status == "pending"
        and database.current.storage_key is None
    )


def test_sync_storage_is_not_executed_on_event_loop_thread():
    from homework_service.infrastructure.file_upload import save_file

    uow, storage, _ = dependencies()
    event_loop_thread = threading.get_ident()
    real_put = storage.put

    def put(*args):
        assert threading.get_ident() != event_loop_thread
        real_put(*args)

    storage.put = put
    asyncio.run(save_file(pending_file(), BytesIO(CONTENT), uow, storage))
