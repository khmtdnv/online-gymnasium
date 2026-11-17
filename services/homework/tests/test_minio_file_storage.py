"""Адаптер хранит поток, освобождает соединения и не раскрывает ошибки SDK."""

from io import BytesIO
from unittest.mock import Mock

import pytest


def storage(client):
    from homework_service.infrastructure.minio_file_storage import MinioFileStorage

    return MinioFileStorage(client, "homework-test")


def test_put_uses_stream_length_type_and_private_key_without_closing_input():
    data = b"answer"
    stream = BytesIO(data)
    client = Mock()

    def receive(**kwargs):
        assert kwargs["bucket_name"] == "homework-test"
        assert kwargs["object_name"] == "homework/1/files/8/attempt"
        assert kwargs["content_type"] == "text/plain"
        assert kwargs["length"] == 6
        assert kwargs["num_parallel_uploads"] == 1
        assert kwargs["data"].read() == data

    client.put_object.side_effect = receive
    storage(client).put("homework/1/files/8/attempt", stream, 6, "text/plain")
    assert not stream.closed


@pytest.mark.parametrize("fail_read", [False, True])
def test_open_releases_connection_on_normal_exit_and_read_error(fail_read):
    client = Mock()
    response = client.get_object.return_value
    response.read.side_effect = OSError("connection lost") if fail_read else None
    response.read.return_value = b"answer"
    try:
        with storage(client).open("homework/1/files/8/attempt") as stream:
            if fail_read:
                with pytest.raises(OSError):
                    stream.read(65536)
            else:
                assert stream.read(65536) == b"answer"
    finally:
        response.close.assert_called_once_with()
        response.release_conn.assert_called_once_with()


@pytest.mark.parametrize("operation", ["put", "open", "delete"])
def test_sdk_failure_becomes_file_io_error(operation):
    from minio.error import ServerError

    client = Mock()
    error = ServerError("secret endpoint", 503)
    method = {"put": "put_object", "open": "get_object", "delete": "remove_object"}[
        operation
    ]
    getattr(client, method).side_effect = error
    adapter = storage(client)
    with pytest.raises(OSError) as caught:
        if operation == "put":
            adapter.put("homework/1/files/8/attempt", BytesIO(b"x"), 1, "text/plain")
        elif operation == "open":
            with adapter.open("homework/1/files/8/attempt"):
                pass
        else:
            adapter.delete("homework/1/files/8/attempt")
    assert "secret" not in str(caught.value)
    assert caught.value.__cause__ is error


def test_delete_uses_only_requested_object():
    client = Mock()
    storage(client).delete("homework/1/files/8/attempt")
    client.remove_object.assert_called_once_with(
        "homework-test", "homework/1/files/8/attempt"
    )


def test_listing_is_lazy_and_limited_to_own_prefix():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    now = datetime.now(UTC)
    client = Mock()
    client.list_objects.return_value = iter(
        [SimpleNamespace(object_name="homework/key", last_modified=now)]
    )
    iterator = storage(client).list_objects("homework/")
    client.list_objects.assert_not_called()
    assert next(iterator) == ("homework/key", now)
    client.list_objects.assert_called_once_with(
        "homework-test", prefix="homework/", recursive=True
    )
    with pytest.raises(ValueError):
        list(storage(client).list_objects("outside/"))


def test_listing_failure_and_invalid_timestamp_fail_closed():
    from types import SimpleNamespace

    client = Mock()
    client.list_objects.return_value = iter(
        [SimpleNamespace(object_name="homework/key", last_modified=None)]
    )
    with pytest.raises(OSError):
        list(storage(client).list_objects("homework/"))


def test_configured_storage_uses_bounded_http_pool_and_closes_it(monkeypatch):
    import homework_service.infrastructure.minio_file_storage as module
    from homework_service.config import HomeworkSettings

    pool = Mock()
    build_pool = Mock(return_value=pool)
    build_client = Mock()
    monkeypatch.setattr(module, "PoolManager", build_pool)
    monkeypatch.setattr(module, "Minio", build_client)
    adapter = module.create_file_storage(
        HomeworkSettings(
            database_url="test",
            minio_endpoint="homework-minio:9000",
            minio_access_key="homework-files",
            minio_secret_key="private-password",
            minio_bucket="homework-files",
            _env_file=None,
        )
    )
    assert build_pool.call_args.kwargs["maxsize"] == 4
    assert build_pool.call_args.kwargs["block"] is True
    assert build_pool.call_args.kwargs["retries"] is False
    assert build_client.call_args.kwargs["secret_key"] == "private-password"
    adapter.close()
    pool.clear.assert_called_once_with()
