"""Настоящий приватный MinIO: байты, multipart и узкие права приложения."""

import hashlib
from io import BytesIO
from secrets import token_hex

import pytest
from minio.error import S3Error

from homework_service.infrastructure.minio_file_storage import create_file_storage
from minio import Minio

pytestmark = pytest.mark.integration


def test_large_file_roundtrip_and_deletion_using_application_credentials(
    minio_settings,
):
    storage = create_file_storage(minio_settings)
    key = f"homework/tests/{token_hex(16)}"
    # Более 5 МиБ: реальный multipart upload SDK, не только маленький PUT.
    data = b"exercise" * 800000
    try:
        storage.put(key, BytesIO(data), len(data), "text/plain")
        digest = hashlib.sha256()
        size = 0
        with storage.open(key) as stream:
            while chunk := stream.read(65536):
                size += len(chunk)
                digest.update(chunk)
        assert size == 6400000
        assert digest.hexdigest() == hashlib.sha256(data).hexdigest()
        storage.delete(key)
        with pytest.raises(OSError), storage.open(key):
            pass
    finally:
        storage.delete(key)
        storage.close()


def test_anonymous_download_and_app_access_outside_homework_prefix_are_denied(
    minio_settings,
):
    settings = minio_settings
    app = Minio(
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key.get_secret_value(),
        secure=False,
        region="us-east-1",
    )
    anonymous = Minio(settings.minio_endpoint, secure=False, region="us-east-1")
    storage = create_file_storage(settings)
    key = f"homework/tests/{token_hex(16)}"
    try:
        storage.put(key, BytesIO(b"answer"), 6, "text/plain")
        with pytest.raises(S3Error) as denied:
            anonymous.get_object(settings.minio_bucket, key)
        assert denied.value.code == "AccessDenied"
        with pytest.raises(S3Error) as denied:
            app.put_object(
                settings.minio_bucket, "outside-homework-prefix", BytesIO(b"x"), 1
            )
        assert denied.value.code == "AccessDenied"
        with pytest.raises(S3Error) as denied:
            app.make_bucket(f"homework-test-forbidden-{token_hex(4)}")
        assert denied.value.code == "AccessDenied"
        with pytest.raises(S3Error) as denied:
            list(app.list_objects(settings.minio_bucket, prefix="outside/"))
        assert denied.value.code == "AccessDenied"
        assert key in [
            item.object_name
            for item in app.list_objects(
                settings.minio_bucket, prefix="homework/", recursive=True
            )
        ]
    finally:
        storage.delete(key)
        storage.close()
        app._http.clear()
        anonymous._http.clear()
