from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


SUPPORTED_FILE_EXTENSIONS = {".md", ".markdown", ".txt", ".docx", ".pdf"}


def extract_file_text(filename: str, content: bytes) -> str:
    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise ValueError("only PDF, DOCX, Markdown, and text files are supported")
    if extension in {".md", ".markdown", ".txt"}:
        return content.decode("utf-8-sig").strip()
    if extension == ".docx":
        with ZipFile(BytesIO(content)) as archive:
            document = archive.read("word/document.xml")
        root = ET.fromstring(document)
        texts = [node.text or "" for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        return "".join(texts).strip()
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF support is unavailable") from exc
    reader = PdfReader(BytesIO(content))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
