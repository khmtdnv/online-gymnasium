"""Короткий TTL включается только в отдельном тестовом MinIO, не в приложении."""

import os
import time
from secrets import token_hex
from urllib.parse import urlsplit

import pytest
from minio.error import S3Error

from minio import Minio

pytestmark = pytest.mark.integration


def test_server_expires_an_abandoned_multipart_upload():
    endpoint = os.getenv("HOMEWORK_TEST_MULTIPART_ENDPOINT")
    if not endpoint:
        pytest.skip("Set endpoint of isolated test MinIO with1s stale upload expiry")
    assert urlsplit(f"http://{endpoint}").hostname in ("127.0.0.1", "localhost")
    client = Minio(
        endpoint,
        "homework-test-root",
        "homework-test-root-password",
        secure=False,
        region="us-east-1",
    )
    bucket = f"homework-test-multipart-{token_hex(4)}"
    key = "homework/test-abandoned"
    upload_id = None
    client.make_bucket(bucket)
    try:
        # SDK private calls only simulate a process dying before CompleteMultipartUpload.
        # Pinned minio7.2.20 signatures are covered by this isolated integration.
        upload_id = client._create_multipart_upload(bucket, key, {})
        client._upload_part(bucket, key, b"unfinished bytes", {}, upload_id, 1)
        assert len(client._list_parts(bucket, key, upload_id).parts) == 1
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                client._list_parts(bucket, key, upload_id)
            except S3Error as exc:
                assert exc.code == "NoSuchUpload"
                break
            time.sleep(0.2)
        else:
            pytest.fail("Test MinIO did not expire abandoned multipart within15s")
        assert list(client.list_objects(bucket, prefix="homework/")) == []
    finally:
        if upload_id is not None:
            try:
                client._abort_multipart_upload(bucket, key, upload_id)
            except S3Error as exc:
                if exc.code != "NoSuchUpload":
                    raise
        client.remove_bucket(bucket)
        client._http.clear()
