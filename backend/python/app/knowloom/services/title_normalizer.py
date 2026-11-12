from __future__ import annotations

from pathlib import Path
import re

_SUFFIX = re.compile(r"[（(]\s*(?:试行|修订稿|征求意见稿|\d{4}\s*年?\s*修订)\s*[）)]\s*$")

def normalize_document_title(value: str) -> str:
    title = Path(str(value or "").strip()).stem
    title = title.strip("《》 ")
    previous = None
    while previous != title:
        previous = title
        title = _SUFFIX.sub("", title).strip()
    return re.sub(r"\s+", "", title).lower()
