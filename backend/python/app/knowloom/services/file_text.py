from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

from app.knowloom.config import PROJECT_DATA_DIR

SUPPORTED_FILE_EXTENSIONS = {".md", ".markdown", ".txt", ".docx", ".pdf"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 300

class FileTooLarge(ValueError): pass
class ScannedPdf(ValueError): pass

@dataclass(slots=True)
class FileConversion:
    text: str
    page_count: int = 0
    page_map: list[dict[str, int]] = field(default_factory=list)


def convert_file(filename: str, content: bytes) -> FileConversion:
    if len(content) > MAX_UPLOAD_BYTES:
        raise FileTooLarge("file exceeds the 20 MB limit")
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise ValueError("only PDF, DOCX, Markdown, and text files are supported")
    if extension in {".md", ".markdown", ".txt"}:
        return FileConversion(content.decode("utf-8-sig").strip())
    if extension == ".docx":
        with ZipFile(BytesIO(content)) as archive:
            document = archive.read("word/document.xml")
        root = ET.fromstring(document)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs: list[str] = []
        for paragraph in root.iter(namespace + "p"):
            text = "".join(node.text or "" for node in paragraph.iter(namespace + "t")).strip()
            if text:
                paragraphs.append(text)
        return FileConversion("\n\n".join(paragraphs))
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(content))
    if len(reader.pages) > MAX_PDF_PAGES:
        raise FileTooLarge("PDF exceeds the 300 page limit")
    page_texts = [page.extract_text() or "" for page in reader.pages]
    sample = page_texts[: min(5, len(page_texts))]
    if sample and all(len(re.sub(r"\s+", "", text)) < 20 for text in sample):
        raise ScannedPdf("scanned PDF without a usable text layer is not supported")
    parts: list[str] = []
    page_map: list[dict[str, int]] = []
    cursor = 0
    for page_no, text in enumerate(page_texts, start=1):
        if parts:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(text)
        cursor += len(text)
        page_map.append({"page": page_no, "char_start": start, "char_end": cursor})
    return FileConversion("".join(parts).strip(), len(page_texts), page_map)


def extract_file_text(filename: str, content: bytes) -> str:
    return convert_file(filename, content).text


def persist_original_file(filename: str, content: bytes) -> str:
    extension = Path(filename or "").suffix.lower()
    digest = sha256(content).hexdigest()
    directory = PROJECT_DATA_DIR / "uploads" / digest[:2]
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(filename or f"upload{extension}").name)
    path = directory / f"{digest}_{safe_name}"
    if not path.exists():
        path.write_bytes(content)
    return str(path)
