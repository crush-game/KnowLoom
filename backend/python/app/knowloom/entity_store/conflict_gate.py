from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.knowloom.constants import AUTO_CONTEXTUAL_MIN_CONFIDENCE, AUTO_TEMPORAL_MIN_CONFIDENCE, ISSUER_LEVEL


@dataclass(frozen=True)
class SourceInfo:
    doc_key: str = ""
    version_no: int = 0
    doc_kind: str = "regulation"
    issuer_level: str = "university"
    published_at: date | None = None
    effective_at: date | None = None
    audience: str = ""

    @property
    def effective_time(self) -> date | None:
        return self.effective_at or self.published_at


@dataclass(frozen=True)
class AttributeWithSources:
    attribute_id: int
    manually_confirmed: bool = False
    sources: tuple[SourceInfo, ...] = field(default_factory=tuple)

    def newest_source(self) -> SourceInfo | None:
        dated = [source for source in self.sources if source.effective_time is not None]
        return max(dated, key=lambda source: source.effective_time) if dated else None


class DocumentRelations(Protocol):
    def amends(self, incoming_doc_key: str, target_doc_key: str) -> bool: ...


class NoDocumentRelations:
    def amends(self, incoming_doc_key: str, target_doc_key: str) -> bool:
        return False


def level(source: SourceInfo) -> int:
    return ISSUER_LEVEL.get(source.issuer_level, 0)


def temporal_outcome(incoming: SourceInfo, target: AttributeWithSources, confidence: float, relations: DocumentRelations) -> str:
    if target.manually_confirmed or confidence < AUTO_TEMPORAL_MIN_CONFIDENCE:
        return "review"
    if target.sources and all(source.doc_key == incoming.doc_key and source.version_no < incoming.version_no for source in target.sources):
        return "supersede_target"
    if target.sources and all(relations.amends(incoming.doc_key, source.doc_key) for source in target.sources):
        return "supersede_target"
    newest = target.newest_source()
    if incoming.effective_time is None or newest is None or newest.effective_time is None:
        return "review"
    if incoming.effective_time > newest.effective_time:
        return "supersede_target" if incoming.doc_kind != "guide" and level(incoming) >= level(newest) else "review"
    if incoming.effective_time < newest.effective_time:
        return "archive_incoming"
    return "review"


def contextual_outcome(target: AttributeWithSources, confidence: float, qualifier_incoming: str, qualifier_target: str, incoming: SourceInfo | None = None) -> tuple[str, str, str]:
    if not qualifier_incoming and incoming is not None:
        qualifier_incoming = incoming.audience
    if not qualifier_target and target.sources:
        qualifier_target = target.sources[-1].audience
    if target.manually_confirmed or confidence < AUTO_CONTEXTUAL_MIN_CONFIDENCE or not qualifier_incoming or not qualifier_target:
        return "review", qualifier_incoming, qualifier_target
    return "qualify", qualifier_incoming, qualifier_target
