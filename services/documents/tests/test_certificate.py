"""Проверяет контракт данных справки независимо от HTTP."""

import pytest

from document_service.domain.certificate import CertificateData, InvalidCertificateData


@pytest.mark.parametrize("field", ["student_full_name", "class_name", "academic_year"])
@pytest.mark.parametrize("value", [None, 1, [], {}])
def test_certificate_rejects_nonstring_fields(field, value):
    data = {
        "student_full_name": "Иван Петров",
        "class_name": "7А",
        "academic_year": "2026/2027",
    }
    data[field] = value
    with pytest.raises(InvalidCertificateData):
        CertificateData(**data)
