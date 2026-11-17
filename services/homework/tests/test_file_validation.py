"""Проверка реальных байтов не доверяет названию, MIME и заявленному размеру."""

import hashlib
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from homework_service.application.homework_files import HomeworkFileInput


def expected_file(
    data: bytes, file_name="Задачи.txt", content_type="text/plain", **changes
):
    """Независимо описывает тестовое содержимое для входного контракта."""
    return HomeworkFileInput(
        **(
            {
                "file_name": file_name,
                "size_bytes": len(data),
                "content_type": content_type,
                "content_sha256": hashlib.sha256(data).hexdigest(),
            }
            | changes
        )
    )


def validate(data: bytes, expected=None):
    from homework_service.infrastructure.file_validation import validate_file

    stream = BytesIO(data)
    return validate_file(
        stream, expected if expected is not None else expected_file(data)
    )


@pytest.mark.parametrize(
    "data", ["Упражнение 1\n".encode(), b"\xef\xbb\xbfAnswer: 42\n"]
)
def test_accepts_utf8_text_and_bom_and_preserves_caller_position(data):
    from homework_service.infrastructure.file_validation import validate_file

    stream = BytesIO(data)
    stream.seek(2)
    assert validate_file(stream, expected_file(data)) == "text/plain"
    assert stream.tell() == 2 and not stream.closed


@pytest.mark.parametrize("data", [b"answer\x00hidden", b"\xff\xfeinvalid", b"text\xc3"])
def test_rejects_binary_or_incomplete_utf8_as_text(data):
    with pytest.raises(ValueError):
        validate(data)


@pytest.mark.parametrize("change", [{"size_bytes": 1}, {"content_sha256": "0" * 64}])
def test_received_content_must_match_reserved_metadata(change):
    data = b"exercise"
    with pytest.raises(ValueError):
        validate(data, expected_file(data, **change))


def test_invalid_format_cannot_be_disguised_as_pdf():
    data = b"%PDF-1.7\nnot a document\n%%EOF"
    with pytest.raises(ValueError):
        validate(data, expected_file(data, "x.pdf", "application/pdf"))


def test_valid_pdf_is_accepted_but_encrypted_pdf_is_not():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    data = stream.getvalue()
    assert (
        validate(data, expected_file(data, "x.pdf", "application/pdf"))
        == "application/pdf"
    )
    writer.encrypt("password")
    stream = BytesIO()
    writer.write(stream)
    data = stream.getvalue()
    with pytest.raises(ValueError):
        validate(data, expected_file(data, "x.pdf", "application/pdf"))


@pytest.mark.parametrize(
    "format,mime,extension",
    [("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpg")],
)
def test_image_is_checked_by_actual_format(format, mime, extension):
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format=format)
    data = stream.getvalue()
    assert validate(data, expected_file(data, f"photo.{extension}", mime)) == mime
    wrong_mime, wrong_extension = (
        ("image/jpeg", "jpg") if format == "PNG" else ("image/png", "png")
    )
    with pytest.raises(ValueError):
        validate(data, expected_file(data, f"photo.{wrong_extension}", wrong_mime))
    data = data[:30]
    with pytest.raises(ValueError):
        validate(data, expected_file(data, f"photo.{extension}", mime))


def ooxml(
    parts=None,
    *,
    main="word/document.xml",
    main_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
):
    """Минимальный ZIP с настоящими content types, без Office automation."""
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/{main}" ContentType="{main_type}"/>'
        "</Types>"
    ).encode()
    roots = {
        "word/document.xml": b'<document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        "ppt/presentation.xml": b'<presentation xmlns="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
    }
    result = BytesIO()
    with ZipFile(result, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in (
            {"[Content_Types].xml": content_types, main: roots[main]} | (parts or {})
        ).items():
            archive.writestr(name, data)
    return result.getvalue()


@pytest.mark.parametrize(
    "extension,main,main_type",
    [
        (
            "docx",
            "word/document.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        ),
        (
            "xlsx",
            "xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        ),
        (
            "pptx",
            "ppt/presentation.xml",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        ),
    ],
)
def test_accepts_supported_ooxml_package(extension, main, main_type):
    from homework_service.domain.homework_file import CONTENT_TYPES

    data = ooxml(main=main, main_type=main_type)
    mime = CONTENT_TYPES[f".{extension}"]
    assert validate(data, expected_file(data, f"exercise.{extension}", mime)) == mime


@pytest.mark.parametrize(
    "parts",
    [
        {"word/vbaProject.bin": b"macro"},
        {"../escape": b"data"},
        {"word/document.xml": b"<!DOCTYPE x [<!ENTITY a 'unsafe'>]><x>&a;</x>"},
        {"[Content_Types].xml": b"not xml"},
        {"word/document.xml": b"0" * 200000},
    ],
)
def test_rejects_unsafe_or_invalid_ooxml_container(parts):
    data = ooxml(parts)
    with pytest.raises(ValueError):
        validate(
            data,
            expected_file(
                data,
                "exercise.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )


def test_different_office_package_cannot_be_renamed_docx():
    data = ooxml(
        main="xl/workbook.xml",
        main_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    )
    with pytest.raises(ValueError):
        validate(
            data,
            expected_file(
                data,
                "exercise.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )


@pytest.mark.parametrize(
    "parts",
    [
        {"word/document.xml": b"<not_a_document/>"},
        {
            "[Content_Types].xml": b'<fake><x PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></fake>'
        },
    ],
)
def test_ooxml_requires_actual_root_namespaces_not_only_named_entries(parts):
    data = ooxml(parts)
    with pytest.raises(ValueError):
        validate(
            data,
            expected_file(
                data,
                "exercise.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        )


def test_validation_reads_input_in_bounded_chunks_and_rewinds_on_error():
    from homework_service.infrastructure.file_validation import validate_file

    class BoundedStream(BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 65536, "whole-file read is forbidden"
            return super().read(size)

    data = b"hello " * 20000
    stream = BoundedStream(data)
    stream.seek(4)
    with pytest.raises(ValueError):
        validate_file(stream, expected_file(data, content_sha256="0" * 64))
    assert stream.tell() == 4 and not stream.closed
