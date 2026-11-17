"""Проверяет входные DTO до запуска генерации документа."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from document_service.application.create_certificate import CreateCertificateCommand
from document_service.application.generate_certificate import GenerateCertificateCommand


@pytest.mark.parametrize("field", ["student_full_name", "class_name", "academic_year"])
@pytest.mark.parametrize("value", ["  ", 123])
def test_certificate_rejects_invalid_field(field, value):
    values = {
        "student_full_name": "Иван",
        "class_name": "7А",
        "academic_year": "2026/2027",
    }
    values[field] = value
    with pytest.raises(ValidationError):
        CreateCertificateCommand(**values)


def test_certificate_preserves_nonblank_spaces():
    command = CreateCertificateCommand(
        student_full_name=" Иван ", class_name=" 7А ", academic_year=" 2026/2027 "
    )
    assert command.student_full_name == " Иван "
    assert command.class_name == " 7А "
    assert command.academic_year == " 2026/2027 "


def test_generate_requires_python_uuid():
    with pytest.raises(ValidationError):
        GenerateCertificateCommand(job_id=str(uuid4()))


def test_generate_is_frozen_and_rejects_extra():
    command = GenerateCertificateCommand(job_id=uuid4())
    with pytest.raises(ValidationError):
        command.job_id = uuid4()
    with pytest.raises(ValidationError):
        GenerateCertificateCommand(job_id=uuid4(), unexpected=True)


def test_pending_task_rejects_naive_time():
    from document_service.application.ports.document_task_outbox_repository import (
        PendingDocumentTask,
    )

    with pytest.raises(ValidationError):
        PendingDocumentTask(
            id=uuid4(),
            document_job_id=uuid4(),
            task_name="generate",
            created_at=datetime(2026, 10, 14, tzinfo=UTC).replace(tzinfo=None),
        )
