"""Контракт ожидаемых вложений без записи байтов и обращения к MinIO."""

from dataclasses import asdict

import pytest
from pydantic import ValidationError

from tests.test_create_homework import command


def file_input(**changes):
    """Возвращает независимое описание выбранного PDF для тестов."""
    return {
        "file_name": "Задачи.pdf",
        "size_bytes": 1024,
        "content_type": "application/pdf",
        "content_sha256": "a" * 64,
    } | changes


@pytest.mark.parametrize("count", [0, 1, 5])
def test_command_accepts_expected_files(count):
    result = command(files=[file_input() for _ in range(count)])
    assert len(result.files) == count
    if count:
        assert result.files[0].file_name == "Задачи.pdf"


def test_command_rejects_six_expected_files():
    with pytest.raises(ValidationError):
        command(files=[file_input() for _ in range(6)])


@pytest.mark.parametrize(
    "change",
    [
        {"size_bytes": 0},
        {"size_bytes": 10485761},
        {"size_bytes": True},
        {"size_bytes": "1024"},
        {"file_name": "../Задачи.pdf"},
        {"file_name": "x\\Задачи.pdf"},
        {"file_name": "x\r\n.pdf"},
        {"file_name": ""},
        {"file_name": "a" * 252 + ".pdf"},
        {"file_name": "x.exe"},
        {"content_type": "image/png"},
        {"content_sha256": "x" * 64},
        {"content_sha256": "a" * 63},
        {"upload_status": "ready"},
        {"storage_key": "someone/else"},
    ],
)
def test_command_rejects_invalid_metadata_before_owner_calls(change):
    with pytest.raises(ValidationError):
        command(files=[file_input(**change)])


def test_command_accepts_exact_size_boundary_and_uppercase_extension():
    result = command(files=[file_input(size_bytes=10485760, file_name="Задачи.PDF")])
    assert result.files[0].size_bytes == 10485760


def test_domain_rejects_ready_file_without_private_key():
    from homework_service.domain.homework_file import HomeworkFile

    with pytest.raises(ValueError):
        HomeworkFile(homework_id=51, upload_status="ready", **file_input())


def test_domain_does_not_accept_bool_ids_or_invalid_digest():
    from homework_service.domain.homework_file import HomeworkFile

    for changes in ({"homework_id": True}, {"content_sha256": "invalid"}):
        with pytest.raises(ValueError):
            HomeworkFile(**({"homework_id": 51} | file_input() | changes))


def test_result_exposes_pending_file_but_not_storage_key_or_digest():
    from homework_service.application.homework_files import HomeworkFileResult
    from homework_service.domain.homework_file import HomeworkFile

    saved = HomeworkFile(homework_id=51, id=8, **file_input())
    result = HomeworkFileResult.from_file(saved).model_dump()
    assert result == {
        "id": 8,
        "homework_id": 51,
        "file_name": "Задачи.pdf",
        "size_bytes": 1024,
        "content_type": "application/pdf",
        "upload_status": "pending",
    }
    assert "storage_key" not in result and "content_sha256" not in result
    assert asdict(saved)["storage_key"] is None


def test_ready_result_requires_persisted_identity():
    from homework_service.application.homework_files import HomeworkFileResult
    from homework_service.domain.homework_file import HomeworkFile

    with pytest.raises(ValidationError):
        HomeworkFileResult.from_file(HomeworkFile(homework_id=51, **file_input()))
