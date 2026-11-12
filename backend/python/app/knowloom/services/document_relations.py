from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class DetectedDocumentRelation:
    relation_type: str
    target_title: str
    evidence: str
    confidence: float = 0.95


RELATION_PATTERNS = (
    ("repeals", re.compile(r"(?P<evidence>(?:同时)?废止[^。；\n]*《(?P<title>[^》]+)》[^。；\n]*)")),
    ("repeals", re.compile(r"(?P<evidence>《(?P<title>[^》]+)》[^。；\n，,]{0,30}(?:同时)?废止)")),
    ("amends", re.compile(r"(?P<evidence>(?:修订|修改)\s*《(?P<title>[^》]+)》[^。；\n]*)")),
    ("implements", re.compile(r"(?P<evidence>(?:实施|落实)\s*《(?P<title>[^》]+)》[^。；\n]*)")),
    ("based_on", re.compile(r"(?P<evidence>(?:依据|根据)\s*《(?P<title>[^》]+)》[^。；\n]*)")),
)


def detect_document_relations(text: str) -> list[DetectedDocumentRelation]:
    results: list[DetectedDocumentRelation] = []
    seen: set[tuple[str, str]] = set()
    for relation_type, pattern in RELATION_PATTERNS:
        for match in pattern.finditer(str(text or "")):
            title = " ".join(match.group("title").split())
            key = (relation_type, title)
            if title and key not in seen:
                seen.add(key)
                results.append(DetectedDocumentRelation(relation_type, title, match.group("evidence").strip()))
    return results
