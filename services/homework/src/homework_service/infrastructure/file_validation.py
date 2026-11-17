"""Ограниченная проверка формата и целостности; не замена антивирусу."""

import codecs
import hashlib
import hmac
import warnings
from pathlib import PurePosixPath
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from homework_service.application.homework_files import HomeworkFileInput

_CHUNK_SIZE = 65536
_MAX_FILE_SIZE = 10485760
_MAX_ZIP_SIZE = 104857600
_MAIN_PARTS = {
    ".docx": (
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    ".xlsx": (
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ),
    ".pptx": (
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ),
}
_MAIN_ROOTS = {
    ".docx": {
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document",
        "{http://purl.oclc.org/ooxml/wordprocessingml/main}document",
    },
    ".xlsx": {
        "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook",
        "{http://purl.oclc.org/ooxml/spreadsheetml/main}workbook",
    },
    ".pptx": {
        "{http://schemas.openxmlformats.org/presentationml/2006/main}presentation",
        "{http://purl.oclc.org/ooxml/presentationml/main}presentation",
    },
}
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def validate_file(stream: BinaryIO, expected: HomeworkFileInput) -> str:
    """Сверяет байты и формат, восстанавливая исходную позицию потока.

    Args:
        stream: Seekable-файл из ограниченного multipart parser; владелец закрывает его.
        expected: Описание из БД, а не заново присланные клиентом метаданные.

    Returns:
        MIME разрешённого и проверенного формата.

    Raises:
        ValueError: Размер, отпечаток или формат не соответствуют ожиданию.
        OSError: Исходный временный файл невозможно прочитать.
    """
    position = stream.tell()
    try:
        stream.seek(0)
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(_CHUNK_SIZE):
            size += len(chunk)
            if size > _MAX_FILE_SIZE or size > expected.size_bytes:
                raise ValueError("File size does not match reserved metadata")
            digest.update(chunk)
        if size != expected.size_bytes or not hmac.compare_digest(
            digest.hexdigest(), expected.content_sha256
        ):
            raise ValueError("File content does not match reserved metadata")
        stream.seek(0)
        suffix = PurePosixPath(expected.file_name).suffix.lower()
        if suffix == ".txt":
            _validate_text(stream)
        elif suffix == ".pdf":
            _validate_pdf(stream)
        elif suffix in (".jpg", ".jpeg", ".png"):
            _validate_image(stream, expected.content_type)
        else:
            _validate_ooxml(stream, suffix)
        return expected.content_type
    except (
        BadZipFile,
        DefusedXmlException,
        PyPdfError,
        UnidentifiedImageError,
        UnicodeError,
        EOFError,
        SyntaxError,
        RecursionError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("Invalid file contents") from exc
    finally:
        stream.seek(position)


def _validate_text(stream: BinaryIO) -> None:
    """Читает UTF-8/BOM по частям, отклоняя NUL и оборванные кодовые последовательности.

    Args:
        stream: Поток с позицией в начале содержимого.

    Raises:
        ValueError: В тексте встречается NUL.
        UnicodeError: Содержимое не UTF-8.
    """
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    while chunk := stream.read(_CHUNK_SIZE):
        if b"\x00" in chunk:
            raise ValueError("NUL is not allowed in text files")
        decoder.decode(chunk)
    decoder.decode(b"", final=True)


def _validate_pdf(stream: BinaryIO) -> None:
    """Проверяет структуру PDF в строгом режиме, не извлекая текст или вложения.

    Args:
        stream: Ограниченный исходный PDF.

    Raises:
        ValueError: Файл зашифрован либо не содержит каталога и дерева страниц.
        PyPdfError: Структура PDF повреждена.
    """
    reader = PdfReader(stream, strict=True)
    if (
        reader.is_encrypted
        or reader.root_object.get("/Type") != "/Catalog"
        or "/Pages" not in reader.root_object
    ):
        raise ValueError("Expected an unencrypted PDF document")


def _validate_image(stream: BinaryIO, content_type: str) -> None:
    """Проверяет PNG/JPEG и ограничивает декодирование сорока миллионами пикселей.

    Args:
        stream: Ограниченный файл изображения.
        content_type: MIME ожидаемого формата.

    Raises:
        ValueError: Несовместимый формат, размер или повреждённое изображение.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream, formats=["PNG", "JPEG"]) as image:
                actual = {"PNG": "image/png", "JPEG": "image/jpeg"}.get(image.format)
                if actual != content_type or image.width * image.height > 40000000:
                    raise ValueError("Unexpected image format or dimensions")
                image.load()
    except (OSError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid image contents") from exc


def _validate_ooxml(stream: BinaryIO, suffix: str) -> None:
    """Проверяет ZIP и XML Office без распаковки путей на диск или выполнения содержимого.

    Args:
        stream: Ограниченный контейнер DOCX/XLSX/PPTX.
        suffix: Подтверждённое разрешённое расширение.

    Raises:
        ValueError: Неверный формат, макросы, шифрование или превышение лимитов.
    """
    main, expected_type = _MAIN_PARTS[suffix]
    with ZipFile(stream) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 2048
            or sum(entry.file_size for entry in entries) > _MAX_ZIP_SIZE
        ):
            raise ValueError("Office container resource limit exceeded")
        names = [entry.filename for entry in entries]
        if (
            len(names) != len(set(names))
            or main not in names
            or "[Content_Types].xml" not in names
        ):
            raise ValueError("Missing or duplicate Office parts")
        found_type = False
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                entry.flag_bits & 1
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or "vbaproject" in entry.filename.lower()
                or entry.file_size > max(1, entry.compress_size) * 100
            ):
                raise ValueError("Unsafe or oversized Office part")
            if entry.is_dir():
                continue
            with archive.open(entry) as part:
                if entry.filename.endswith((".xml", ".rels")):
                    depth = count = 0
                    for event, element in iterparse(
                        part, events=("start", "end"), forbid_dtd=True
                    ):
                        if event == "start":
                            depth += 1
                            count += 1
                            if depth > 128 or count > 200000:
                                raise ValueError("Office XML resource limit exceeded")
                            if count == 1:
                                if (
                                    entry.filename == main
                                    and element.tag not in _MAIN_ROOTS[suffix]
                                ):
                                    raise ValueError("Unexpected Office document root")
                                if (
                                    entry.filename == "[Content_Types].xml"
                                    and element.tag != f"{{{_CONTENT_TYPES_NS}}}Types"
                                ):
                                    raise ValueError(
                                        "Unexpected Office content types root"
                                    )
                        else:
                            if entry.filename == "[Content_Types].xml":
                                value = element.attrib.get("ContentType", "")
                                if (
                                    "macroenabled" in value.lower()
                                    or "vbaproject" in value.lower()
                                ):
                                    raise ValueError("Office macros are not supported")
                                if (
                                    element.tag == f"{{{_CONTENT_TYPES_NS}}}Override"
                                    and element.attrib.get("PartName") == f"/{main}"
                                    and value == expected_type
                                ):
                                    found_type = True
                            element.clear()
                            depth -= 1
                else:
                    consumed = 0
                    while chunk := part.read(_CHUNK_SIZE):
                        consumed += len(chunk)
                        if consumed > entry.file_size or consumed > _MAX_ZIP_SIZE:
                            raise ValueError("Office part exceeds declared size")
        if not found_type:
            raise ValueError("Office main document type does not match extension")
